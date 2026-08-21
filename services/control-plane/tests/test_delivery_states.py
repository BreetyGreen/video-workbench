from app.models import DeliveryState


def test_delivery_states_distinguish_local_draft_and_published_videos():
    values = {state.value for state in DeliveryState}

    assert values == {"jianying_draft", "douyin_self_visible", "douyin_published"}
    assert "douyin_draft" not in values
