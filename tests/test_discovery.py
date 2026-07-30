from sniff import discovery


def test_discover_returns_all_builtin_detectors():
    detectors, errors = discovery.discover()
    names = {d.name for d in detectors}
    assert errors == []
    assert {"largest-methods", "cognitive-complexity", "no-duplicate-string",
            "sniff-patterns"} <= names
    assert len(names) >= 11


def test_builtin_detectors_expose_module_main():
    detectors, _ = discovery.discover()
    for d in detectors:
        if d.module is not None:
            assert callable(d.module.main), d.name
