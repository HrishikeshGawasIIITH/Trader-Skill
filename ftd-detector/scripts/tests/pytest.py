"""Tiny stand-in for the parts of pytest these tests use, so that
`python -m unittest discover -s <tests dir>` runs them with the stdlib only.

Supports: fixtures (module, class and conftest.py, generators, params, autouse),
parametrize, raises, approx, skip marks, and the tmp_path, monkeypatch and
capsys built-ins. Each test module ends with:

    import pytest as _pt
    load_tests = _pt.make_load_tests(__name__)
"""

import contextlib
import importlib.util
import inspect
import io
import itertools
import math
import os
import pathlib
import re
import shutil
import sys
import tempfile
import unittest

_MISSING = object()


# --- decorators and helpers -----------------------------------------------


def fixture(func=None, *, scope=None, params=None, autouse=False, name=None, ids=None):
    def wrap(f):
        f._pt_fixture = True
        f._pt_params = list(params) if params is not None else None
        f._pt_autouse = autouse
        f._pt_name = name or f.__name__
        return f

    return wrap(func) if func is not None else wrap


class _Mark:
    def parametrize(self, argnames, argvalues, ids=None):
        def wrap(f):
            lst = getattr(f, "_pt_parametrize", [])
            f._pt_parametrize = lst + [(argnames, list(argvalues))]
            return f

        return wrap

    def skip(self, reason="", **kw):
        if callable(reason):
            reason._pt_skip = "skipped"
            return reason

        def wrap(f):
            f._pt_skip = reason
            return f

        return wrap

    def skipif(self, cond, reason="", **kw):
        def wrap(f):
            if cond:
                f._pt_skip = reason or "skipif"
            return f

        return wrap

    def __getattr__(self, name):
        def deco(*a, **k):
            if len(a) == 1 and callable(a[0]) and not k:
                return a[0]
            return lambda f: f

        return deco


mark = _Mark()


def skip(reason=""):
    raise unittest.SkipTest(reason)


def importorskip(name):
    try:
        return __import__(name)
    except ImportError:
        raise unittest.SkipTest(f"no module {name}")


class _RaisesInfo:
    value = None


class raises:
    def __init__(self, exc, match=None):
        self.exc = exc
        self.match = match
        self.info = _RaisesInfo()

    def __enter__(self):
        return self.info

    def __exit__(self, et, ev, tb):
        if et is None:
            raise AssertionError(f"DID NOT RAISE {self.exc}")
        if not issubclass(et, self.exc):
            return False
        if self.match is not None and not re.search(self.match, str(ev)):
            raise AssertionError(f"pattern {self.match!r} not found in {str(ev)!r}")
        self.info.value = ev
        return True


class approx:
    def __init__(self, expected, rel=None, abs=None):
        self.expected = expected
        self.rel = rel
        self.abs = abs

    def _close(self, a, b):
        if isinstance(b, (list, tuple)):
            return len(a) == len(b) and all(self._close(x, y) for x, y in zip(a, b))
        if isinstance(b, dict):
            return a.keys() == b.keys() and all(self._close(a[k], b[k]) for k in b)
        if a is None or b is None:
            return a is b
        tol_abs = self.abs if self.abs is not None else 1e-12
        tol_rel = self.rel if self.rel is not None else 1e-6
        tol = max(tol_abs, tol_rel * math.fabs(b)) if self.rel is not None or self.abs is None else tol_abs
        if self.abs is not None and self.rel is None:
            tol = self.abs
        return a == b or math.fabs(a - b) <= tol

    def __eq__(self, other):
        return self._close(other, self.expected)

    def __repr__(self):
        return f"approx({self.expected!r})"


# --- built-in fixtures ----------------------------------------------------


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name=_MISSING, value=_MISSING, raising=True):
        if value is _MISSING:  # setattr("a.b.c", value)
            value = name
            path, _, attr = target.rpartition(".")
            parts = path.split(".")
            obj = __import__(parts[0])
            for p in parts[1:]:
                try:
                    obj = getattr(obj, p)
                except AttributeError:
                    obj = __import__(".".join(parts[: parts.index(p) + 1]), fromlist=["x"])
            target, name = obj, attr
        old = getattr(target, name, _MISSING)
        if old is _MISSING and raising:
            raise AttributeError(name)
        self._undo.append(lambda t=target, n=name, o=old: delattr(t, n) if o is _MISSING else setattr(t, n, o))
        setattr(target, name, value)

    def delattr(self, target, name, raising=True):
        old = getattr(target, name, _MISSING)
        if old is _MISSING:
            if raising:
                raise AttributeError(name)
            return
        self._undo.append(lambda t=target, n=name, o=old: setattr(t, n, o))
        delattr(target, name)

    def setenv(self, name, value, prepend=None):
        old = os.environ.get(name, _MISSING)
        self._undo.append(
            lambda n=name, o=old: os.environ.pop(n, None) if o is _MISSING else os.environ.__setitem__(n, o)
        )
        os.environ[name] = str(value)

    def delenv(self, name, raising=True):
        old = os.environ.get(name, _MISSING)
        if old is _MISSING:
            if raising:
                raise KeyError(name)
            return
        self._undo.append(lambda n=name, o=old: os.environ.__setitem__(n, o))
        del os.environ[name]

    def setitem(self, d, key, value):
        old = d.get(key, _MISSING)
        self._undo.append(lambda: d.pop(key, None) if old is _MISSING else d.__setitem__(key, old))
        d[key] = value

    def delitem(self, d, key, raising=True):
        if key not in d:
            if raising:
                raise KeyError(key)
            return
        old = d[key]
        self._undo.append(lambda: d.__setitem__(key, old))
        del d[key]

    def chdir(self, path):
        old = os.getcwd()
        self._undo.append(lambda: os.chdir(old))
        os.chdir(str(path))

    def syspath_prepend(self, path):
        old = list(sys.path)
        self._undo.append(lambda: sys.path.__setitem__(slice(None), old))
        sys.path.insert(0, str(path))

    def undo(self):
        while self._undo:
            self._undo.pop()()


class _CapResult:
    def __init__(self, out, err):
        self.out, self.err = out, err


class CaptureFixture:
    def __init__(self):
        self._out, self._err = io.StringIO(), io.StringIO()
        self._o, self._e = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = self._out, self._err

    def readouterr(self):
        r = _CapResult(self._out.getvalue(), self._err.getvalue())
        self._out.seek(0)
        self._out.truncate()
        self._err.seek(0)
        self._err.truncate()
        return r

    def close(self):
        sys.stdout, sys.stderr = self._o, self._e


# --- collection -----------------------------------------------------------


def _is_fixture(obj):
    return getattr(obj, "_pt_fixture", False)


def _load_conftest(modname):
    mod = sys.modules.get(modname)
    base = os.path.dirname(os.path.abspath(sys.modules[modname].__file__))
    path = os.path.join(base, "conftest.py")
    if not os.path.isfile(path):
        return {}
    spec = importlib.util.spec_from_file_location("conftest_" + str(abs(hash(path))), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {n: o for n, o in vars(m).items() if _is_fixture(o)}


class _Ctx:
    """Per-test fixture resolver."""

    def __init__(self, sources, instance):
        self.sources = sources  # list of dicts name->fixture func (first wins)
        self.instance = instance
        self.cache = {}
        self.finalizers = []
        self.monkey = None

    def get(self, name, override=None):
        if override and name in override:
            return override[name]
        if name in self.cache:
            return self.cache[name]
        if name == "tmp_path":
            d = pathlib.Path(tempfile.mkdtemp())
            self.finalizers.append(lambda: shutil.rmtree(d, ignore_errors=True))
            val = d
        elif name == "tmpdir":
            d = tempfile.mkdtemp()
            self.finalizers.append(lambda: shutil.rmtree(d, ignore_errors=True))
            val = pathlib.Path(d)
        elif name == "monkeypatch":
            val = MonkeyPatch()
            self.finalizers.append(val.undo)
        elif name in ("capsys", "capfd"):
            val = CaptureFixture()
            self.finalizers.append(val.close)
        else:
            func = None
            for src in self.sources:
                if name in src:
                    func = src[name]
                    break
            if func is None:
                raise LookupError(f"fixture {name!r} not found")
            val = self._call(func, override)
        self.cache[name] = val
        return val

    def _call(self, func, override):
        sig = inspect.signature(func)
        kwargs = {}
        for pname in sig.parameters:
            if pname == "self":
                continue
            if pname == "request":
                kwargs[pname] = type("Req", (), {"param": (override or {}).get("request_param")})()
                continue
            kwargs[pname] = self.get(pname, override)
        if inspect.ismethod(func) or "self" in sig.parameters:
            res = func(self.instance, **kwargs) if "self" in sig.parameters else func(**kwargs)
        else:
            res = func(**kwargs)
        if inspect.isgenerator(res):
            val = next(res)

            def fin(g=res):
                try:
                    next(g)
                except StopIteration:
                    pass

            self.finalizers.append(fin)
            return val
        return res

    def close(self):
        while self.finalizers:
            try:
                self.finalizers.pop()()
            except Exception:
                pass


def _make_case(label, func, cls, modfix, conf, skip_reason, call_kwargs, fix_override):
    class Case(unittest.TestCase):
        def runTest(self):
            if skip_reason:
                self.skipTest(str(skip_reason))
            instance = cls() if cls is not None else None
            sources = []
            if cls is not None:
                sources.append({n: o for n, o in vars(cls).items() if _is_fixture(o)})
            sources += [modfix, conf]
            ctx = _Ctx(sources, instance)
            try:
                for src in sources:
                    for n, f in list(src.items()):
                        if getattr(f, "_pt_autouse", False):
                            ctx.get(n, fix_override)
                if instance is not None and hasattr(instance, "setup_method"):
                    instance.setup_method(func)
                sig = inspect.signature(func)
                kwargs = {}
                for pname in sig.parameters:
                    if pname == "self":
                        continue
                    if pname in call_kwargs:
                        kwargs[pname] = call_kwargs[pname]
                    else:
                        kwargs[pname] = ctx.get(pname, fix_override)
                bound = func.__get__(instance, cls) if instance is not None else func
                bound(**kwargs)
                if instance is not None and hasattr(instance, "teardown_method"):
                    instance.teardown_method(func)
            finally:
                ctx.close()

        def id(self):
            return label

        def shortDescription(self):
            return label

    return Case()


def _expand(func):
    """Yield (suffix, call_kwargs) for parametrize stacks."""
    marks = getattr(func, "_pt_parametrize", [])
    if not marks:
        yield "", {}
        return
    groups = []
    for argnames, values in marks:
        names = [n.strip() for n in argnames.split(",")] if isinstance(argnames, str) else list(argnames)
        rows = []
        for i, v in enumerate(values):
            if getattr(v, "__class__", None).__name__ == "ParamSet":
                v = v.values
            vals = (v,) if len(names) == 1 else tuple(v)
            rows.append((i, dict(zip(names, vals))))
        groups.append(rows)
    for combo in itertools.product(*groups):
        kw = {}
        for _, d in combo:
            kw.update(d)
        yield "[" + "-".join(str(i) for i, _ in combo) + "]", kw


def param(*values, id=None, marks=()):
    class ParamSet:
        pass

    p = ParamSet()
    p.values = values if len(values) > 1 else values[0]
    if len(values) == 1:
        p.values = values[0]
    return p


def make_load_tests(modname):
    def load_tests(loader, standard_tests, pattern):
        suite = unittest.TestSuite()
        for t in standard_tests:
            suite.addTest(t)
        module = sys.modules[modname]
        conf = _load_conftest(modname)
        modfix = {n: o for n, o in vars(module).items() if _is_fixture(o)}

        def add(label, func, cls):
            skip_reason = getattr(func, "_pt_skip", None) or (cls is not None and getattr(cls, "_pt_skip", None))
            # fixture params
            fixture_params = []
            sig = inspect.signature(func)
            for pname in sig.parameters:
                for src in (modfix, conf):
                    f = src.get(pname)
                    if f is not None and f._pt_params:
                        fixture_params.append((pname, f._pt_params))
            for suffix, kw in _expand(func):
                if fixture_params:
                    names = [n for n, _ in fixture_params]
                    for i, combo in enumerate(itertools.product(*[p for _, p in fixture_params])):
                        ov = dict(zip(names, combo))
                        ov["request_param"] = combo[0]
                        suite.addTest(
                            _make_case(f"{label}{suffix}[{i}]", func, cls, modfix, conf, skip_reason, kw, ov)
                        )
                else:
                    suite.addTest(_make_case(label + suffix, func, cls, modfix, conf, skip_reason, kw, None))

        for name, obj in list(vars(module).items()):
            if inspect.isfunction(obj) and name.startswith("test") and not _is_fixture(obj):
                if obj.__module__ == modname:
                    add(f"{modname}.{name}", obj, None)
            elif inspect.isclass(obj) and name.startswith("Test") and obj.__module__ == modname:
                if issubclass(obj, unittest.TestCase):
                    continue
                for mname, m in list(vars(obj).items()):
                    if inspect.isfunction(m) and mname.startswith("test") and not _is_fixture(m):
                        add(f"{modname}.{name}.{mname}", m, obj)
        return suite

    return load_tests


# Load conftest.py next to this file once, so its sys.path setup applies.
_here = os.path.dirname(os.path.abspath(__file__))
if os.path.isfile(os.path.join(_here, "conftest.py")) and "conftest" not in sys.modules:
    try:
        _spec = importlib.util.spec_from_file_location("conftest", os.path.join(_here, "conftest.py"))
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["conftest"] = _mod
        _spec.loader.exec_module(_mod)
    except Exception:
        sys.modules.pop("conftest", None)
