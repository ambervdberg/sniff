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


def test_external_detector_discovered_from_scan_path(tmp_path):
    d = tmp_path / ".sniff" / "detectors" / "my-det"
    d.mkdir(parents=True)
    (d / "detector.yml").write_text(
        "name: my-det\ntitle: My detector\nscript: run_me.py\n", encoding="utf-8")
    (d / "run_me.py").write_text("print('hi')\n", encoding="utf-8")

    detectors, errors = discovery.discover(str(tmp_path))
    assert errors == []
    ext = next(x for x in detectors if x.name == "my-det")
    assert ext.module is None and ext.script.endswith("run_me.py")


def test_external_detector_shadowing_builtin_is_error(tmp_path):
    d = tmp_path / ".sniff" / "detectors" / "largest-methods"
    d.mkdir(parents=True)
    (d / "detector.yml").write_text(
        "name: largest-methods\nscript: x.py\n", encoding="utf-8")
    (d / "x.py").write_text("", encoding="utf-8")

    detectors, errors = discovery.discover(str(tmp_path))
    assert any("shadows built-in" in e for e in errors)
    assert sum(1 for x in detectors if x.name == "largest-methods") == 1
