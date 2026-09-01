from types import SimpleNamespace

from boarding_pass_service.dependencies import (
    get_locations,
    get_session_master,
    get_session_slave,
    get_settings,
)


def fake_request(**state):
    # the dependencies only reach into app.state, so a stand in is enough
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))


def test_dependencies_read_from_app_state():
    request = fake_request(
        settings="the-settings",
        session_master="the-master-factory",
        session_slave="the-slave-factory",
        locations="the-locations-client",
    )

    assert get_settings(request) == "the-settings"
    assert get_locations(request) == "the-locations-client"
    # writes on master, reads on slave - mixing these up would be silent, so it is asserted
    assert get_session_master(request) == "the-master-factory"
    assert get_session_slave(request) == "the-slave-factory"
