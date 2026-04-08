from __future__ import annotations

import pytest

from symphony.config import load_config
from symphony.models import InstrumentName
from symphony.orchestra import Orchestra
from symphony.orchestra.refresh import refresh_provider_models


class TestRefreshProviderModels:
    @pytest.mark.asyncio()
    async def test_adds_musicians_for_new_models(self, config_path, loaded_config) -> None:
        orchestra = Orchestra(loaded_config)
        await orchestra.start()
        try:
            assert (InstrumentName.CLAUDE, "sonnet") not in orchestra.musicians

            # Simulate discovery having written a new model to config.toml.
            text = config_path.read_text(encoding="utf-8")
            text = text.replace(
                'models = ["opus", "haiku"]',
                'models = ["opus", "haiku", "sonnet"]',
            )
            config_path.write_text(text, encoding="utf-8")

            changed = await refresh_provider_models(orchestra, InstrumentName.CLAUDE)

            assert changed is True
            assert (InstrumentName.CLAUDE, "sonnet") in orchestra.musicians
            pool = orchestra.musicians[(InstrumentName.CLAUDE, "sonnet")]
            assert len(pool) == 1
            assert pool[0].ready
        finally:
            await orchestra.stop()

    @pytest.mark.asyncio()
    async def test_removes_idle_musicians(self, config_path, loaded_config) -> None:
        orchestra = Orchestra(loaded_config)
        await orchestra.start()
        try:
            assert (InstrumentName.CLAUDE, "haiku") in orchestra.musicians

            # Remove "haiku" from the config on disk.
            text = config_path.read_text(encoding="utf-8")
            text = text.replace(
                'models = ["opus", "haiku"]',
                'models = ["opus"]',
            )
            config_path.write_text(text, encoding="utf-8")

            changed = await refresh_provider_models(orchestra, InstrumentName.CLAUDE)

            assert changed is True
            assert (InstrumentName.CLAUDE, "haiku") not in orchestra.musicians
        finally:
            await orchestra.stop()

    @pytest.mark.asyncio()
    async def test_preserves_busy_musicians(self, config_path, loaded_config) -> None:
        orchestra = Orchestra(loaded_config)
        await orchestra.start()
        try:
            # Mark the haiku musician as busy.
            haiku_pool = orchestra.musicians[(InstrumentName.CLAUDE, "haiku")]
            haiku_pool[0].busy = True

            text = config_path.read_text(encoding="utf-8")
            text = text.replace(
                'models = ["opus", "haiku"]',
                'models = ["opus"]',
            )
            config_path.write_text(text, encoding="utf-8")

            changed = await refresh_provider_models(orchestra, InstrumentName.CLAUDE)

            assert changed is True
            # Pool still exists because the musician is busy.
            assert (InstrumentName.CLAUDE, "haiku") in orchestra.musicians
        finally:
            await orchestra.stop()

    @pytest.mark.asyncio()
    async def test_no_change_returns_false(self, loaded_config) -> None:
        orchestra = Orchestra(loaded_config)
        await orchestra.start()
        try:
            changed = await refresh_provider_models(orchestra, InstrumentName.CLAUDE)
            assert changed is False
        finally:
            await orchestra.stop()
