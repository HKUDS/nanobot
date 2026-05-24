from nanobot.utils.image_generation_intent import image_generation_prompt


def test_image_generation_prompt_ignores_plain_messages() -> None:
    assert image_generation_prompt("hello", {}) == "hello"


def test_image_generation_prompt_uses_auto_aspect_instruction() -> None:
    prompt = image_generation_prompt(
        "Draw a poster",
        {"image_generation": {"enabled": True, "aspect_ratio": None}},
    )

    assert "Draw a poster" in prompt
    assert "Use the generate_image tool" in prompt
    assert "Choose the most suitable aspect_ratio yourself" in prompt


def test_image_generation_prompt_uses_selected_aspect_ratio() -> None:
    prompt = image_generation_prompt(
        "Draw a banner",
        {"image_generation": {"enabled": True, "aspect_ratio": "16:9"}},
    )

    assert "aspect_ratio='16:9'" in prompt
