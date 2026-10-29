"""A2A protocol channel descriptor."""

from nanobot.channels.plugin import ChannelPlugin

PLUGIN = ChannelPlugin(
    name="a2a",
    display_name="A2A",
    runtime=f"{__package__}.runtime:A2AChannel",
    dependencies=("a2a-sdk[http-server]>=0.2.0,<1.0.0",),
)
