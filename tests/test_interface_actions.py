from nethack_interface.actions import Action, RawAction, action_spec


def test_action_spec_derives_core_actions_from_registry():
    spec = action_spec()
    # core actions present, each with an arg schema sourced from the registry
    for name in ("move", "move_to"):
        assert name in spec
    assert isinstance(spec["move_to"], dict)  # the registry schema


def test_typed_action_and_raw_action():
    a = Action("move_to", {"x": 5, "y": 9})
    assert a.name == "move_to" and a.args == {"x": 5, "y": 9}
    r = RawAction(12)
    assert r.index == 12
