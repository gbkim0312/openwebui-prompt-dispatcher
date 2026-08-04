from prompt_dispatcher.bootstrap.container import _configured_talk_rooms


def test_configured_talk_rooms_reads_multiple_valid_targets() -> None:
    targets = _configured_talk_rooms(
        {
            "NEXTCLOUD_TALK_ROOMS": (
                '[{"id":"team-news","name":"팀 공지","room_token":"room-1"}]'
            ),
            "NEXTCLOUD_TALK_PERSONAL_USERNAME": "bot",
            "NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD": "secret",
        }
    )

    assert targets == {"team-news": ("bot", "secret", "room-1")}
