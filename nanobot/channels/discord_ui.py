"""Discord UI components for nanobot slash commands."""

from collections.abc import Awaitable, Callable

import discord


class ModelModal(discord.ui.Modal, title="Set Model"):
    model_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Model name",
        placeholder="e.g. claude-opus-4-6",
        required=True,
        max_length=200,
    )

    def __init__(self, provider: str, on_confirm: Callable[[str, str], Awaitable[None]]) -> None:
        super().__init__()
        self._provider = provider
        self._on_confirm = on_confirm

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._on_confirm(self._provider, self.model_name.value)
        await interaction.followup.send(
            f"✓ Model set to `{self._provider}/{self.model_name.value}`",
            ephemeral=True,
        )


class ProviderSelect(discord.ui.Select):
    def __init__(self, providers: list[tuple[str, str]], parent_view: "ModelPickerView") -> None:
        # providers = [(name, display_label), ...]
        options = [discord.SelectOption(label=label, value=name) for name, label in providers[:25]]
        super().__init__(placeholder="Select provider…", options=options, min_values=1, max_values=1)
        self._parent = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._parent._selected_provider = self.values[0]
        await interaction.response.defer()


class ModelPickerView(discord.ui.View):
    def __init__(
        self,
        providers: list[tuple[str, str]],
        on_confirm: Callable[[str, str], Awaitable[None]],
    ) -> None:
        super().__init__(timeout=600.0)
        self._selected_provider: str | None = None
        self._on_confirm = on_confirm
        self._select = ProviderSelect(providers, self)
        self.add_item(self._select)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]

    @discord.ui.button(label="Set Model", style=discord.ButtonStyle.primary, row=1)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not self._selected_provider:
            await interaction.response.send_message(
                "Please select a provider first.", ephemeral=True
            )
            return
        modal = ModelModal(provider=self._selected_provider, on_confirm=self._on_confirm)
        await interaction.response.send_modal(modal)


class StopButton(discord.ui.Button):
    def __init__(self, on_stop: Callable[[], Awaitable[None]]) -> None:
        super().__init__(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
        self._on_stop = on_stop

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        self.disabled = True
        if self.view:
            await interaction.message.edit(view=self.view)
        await self._on_stop()
        await interaction.followup.send("Stopping…", ephemeral=True)


class StatusView(discord.ui.View):
    def __init__(self, on_stop: Callable[[], Awaitable[None]]) -> None:
        super().__init__(timeout=300.0)
        self.add_item(StopButton(on_stop))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]


class McpServerSelect(discord.ui.Select):
    def __init__(self, servers: list[str]) -> None:
        if servers:
            options = [discord.SelectOption(label=s, value=s) for s in servers[:25]]
            disabled = False
        else:
            options = [discord.SelectOption(label="(no servers configured)", value="none")]
            disabled = True
        super().__init__(
            placeholder="Select MCP server…",
            options=options,
            min_values=1,
            max_values=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class McpView(discord.ui.View):
    def __init__(self, servers: list[str]) -> None:
        super().__init__(timeout=300.0)
        self.add_item(McpServerSelect(servers))
