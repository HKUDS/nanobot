"""Internal markers for identifying model-facing user inputs."""

CONSUMED_INPUT_CURSOR_KEY = "_model_consumed_input"
MODEL_INPUT_ROLE_KEY = "_is_user_input"
MODEL_INPUT_AFTER_CURSOR_KEY = "_model_input_after_cursor"
# Request-local provenance survives adjacent-user message merging, but is not persisted.
MODEL_INPUT_POSITION_KEY = "_model_input_position"
MODEL_INPUT_FRESH_KEY = "_model_input_fresh"
