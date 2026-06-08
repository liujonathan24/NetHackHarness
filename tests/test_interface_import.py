def test_package_imports():
    import nethack_interface
    assert hasattr(nethack_interface, "__version__")
