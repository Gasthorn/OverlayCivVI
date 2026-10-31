"""Validation et typage des messages game_state (spec 01 §5)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import contracts


class InvalidGameState(ValueError):
    """Message reçu du mod illisible ou non conforme au schéma."""


@dataclass(frozen=True)
class Yields:
    gold: float | None
    gold_per_turn: float | None
    science_per_turn: float | None
    culture_per_turn: float | None
    faith: float | None
    faith_per_turn: float | None


@dataclass(frozen=True)
class DistrictSite:
    """Meilleur emplacement d'un quartier dans une ville, adjacence calculée par le jeu."""
    adjacency: float
    hex_x: int
    hex_y: int


@dataclass(frozen=True)
class CityPlot:
    """Tuile de la carte détaillée d'une ville (spec 01 §5, `cities[].plots`)."""
    index: int
    hex_x: int
    hex_y: int
    terrain: str
    owned: bool
    neighbors: tuple[int, ...] = ()
    feature: str | None = None
    resource: str | None = None
    improvement: str | None = None
    district: str | None = None
    river: bool = False
    foreign: bool = False  # appartient à une autre civilisation : aucun quartier possible
    other_city: str | None = None  # nom d'une autre ville du joueur qui possède la tuile
    # Quartiers absents de la ville que la tuile peut accueillir -> adjacence calculée par le jeu.
    sites: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DistrictSlots:
    used: int
    allowed: int


@dataclass(frozen=True)
class City:
    city_id: int
    name: str
    hex_x: int
    hex_y: int
    population: int
    is_capital: bool = False
    housing: float | None = None
    amenities_surplus: int | None = None
    coastal: bool | None = None  # None : inconnu (état antérieur au champ)
    current_production: str | None = None
    production_turns_left: float | None = None
    districts: frozenset[str] = frozenset()
    buildings: frozenset[str] = frozenset()
    # None : non exporté (état antérieur au champ) ; {} : aucun emplacement valide.
    district_sites: dict[str, DistrictSite] | None = None
    district_slots: DistrictSlots | None = None
    # Carte détaillée : exportée seulement en début de tour (None sinon).
    plots: tuple[CityPlot, ...] | None = None
    # Merveilles lançables maintenant -> indices des tuiles où le jeu autorise à les placer
    # (début de tour seulement, comme `plots`).
    wonder_sites: dict[str, tuple[int, ...]] | None = None


@dataclass(frozen=True)
class Unit:
    unit_id: int
    type: str
    hex_x: int
    hex_y: int


@dataclass(frozen=True)
class Tile:
    hex_x: int
    hex_y: int
    terrain: str
    visible: bool
    feature: str | None = None
    resource: str | None = None
    improvement: str | None = None
    owner: str | None = None
    river: bool = False


@dataclass(frozen=True)
class SettleTile:
    """Tuile révélée autour des villes et des colons (spec 01 §5, `settle_map`)."""
    hex_x: int
    hex_y: int
    terrain: str
    feature: str | None = None
    natural_wonder: bool = False
    river: bool = False
    lake: bool = False
    owner: str | None = None  # "self" | "other" | None
    city: str | None = None   # "self" | "other" : centre-ville sur la tuile
    resource: str | None = None


@dataclass(frozen=True)
class SettleMap:
    map_width: int
    map_height: int
    tiles: tuple[SettleTile, ...]
    # Convention de grille, déduite des cartes de villes par le moteur (CityPlotsCache.enrich).
    odd_shifted: bool = True


@dataclass(frozen=True)
class KnownPlayer:
    player_id: int
    civilization: str
    leader: str
    at_war: bool = False
    name: str | None = None  # nom affiché en jeu (inclut les civilisations de mods)


@dataclass(frozen=True)
class GameState:
    schema_version: int
    trigger: str
    game_id: str | None
    turn: int
    player_id: int
    civilization: str
    leader: str
    yields: Yields
    current_research: str | None
    era: str | None
    raw: dict[str, Any]
    game_speed: str | None = None
    government: str | None = None
    religion: str | None = None
    research_progress: float | None = None
    research_cost: float | None = None
    researched: frozenset[str] = frozenset()
    boosted_techs: frozenset[str] = frozenset()
    # None : section civics absente (MVP 0 ou extraction en échec).
    current_civic: str | None = None
    civic_progress: float | None = None
    civic_cost: float | None = None
    civics_unlocked: frozenset[str] | None = None
    boosted_civics: frozenset[str] = frozenset()
    cities: tuple[City, ...] = ()
    units: tuple[Unit, ...] = ()
    tiles: tuple[Tile, ...] = ()
    known_players: tuple[KnownPlayer, ...] = ()
    strategic_resources: dict[str, float] = field(default_factory=dict)
    # Carte de colonisation : début de tour seulement (None sinon).
    settle_map: SettleMap | None = None


def _pick(cls: type, data: dict[str, Any], **overrides: Any) -> Any:
    """Construit une dataclass à partir des seuls champs connus."""
    known = cls.__dataclass_fields__
    values = {k: v for k, v in data.items() if k in known}
    values.update(overrides)
    return cls(**values)


def _parse_city(data: dict[str, Any]) -> City:
    sites = data.get("district_sites")
    slots = data.get("district_slots")
    plots = data.get("plots")
    wonders = data.get("wonder_sites")
    return _pick(
        City, data,
        wonder_sites=None if wonders is None else {k: tuple(v) for k, v in wonders.items()},
        districts=frozenset(data.get("districts", ())),
        buildings=frozenset(data.get("buildings", ())),
        district_sites=None if sites is None else {k: _pick(DistrictSite, v) for k, v in sites.items()},
        district_slots=None if slots is None else _pick(DistrictSlots, slots),
        plots=None if plots is None else tuple(
            _pick(CityPlot, p, neighbors=tuple(p.get("neighbors", ())), sites=dict(p.get("sites", {})))
            for p in plots
        ),
    )


def parse_game_state(payload: bytes) -> GameState:
    """Décode, valide et type un game_state. Lève InvalidGameState en cas de problème."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidGameState(f"JSON illisible : {exc}") from exc

    error = contracts.first_error("game_state", data)
    if error is not None:
        raise InvalidGameState(f"Non conforme au schéma : {error}")

    meta, game, player, techs = data["meta"], data["game"], data["player"], data["techs"]
    civics = data.get("civics")
    return GameState(
        schema_version=data["schema_version"],
        trigger=meta["trigger"],
        game_id=meta.get("game_id"),
        turn=game["turn"],
        player_id=player["player_id"],
        civilization=player["civilization"],
        leader=player["leader"],
        yields=_pick(Yields, data["yields"]),
        current_research=techs["current_research"],
        era=game.get("era"),
        raw=data,
        game_speed=game.get("game_speed"),
        government=player.get("government"),
        religion=player.get("religion"),
        research_progress=techs.get("research_progress"),
        research_cost=techs.get("research_cost"),
        researched=frozenset(techs.get("researched", ())),
        boosted_techs=frozenset(techs.get("boosted", ())),
        current_civic=civics["current_civic"] if civics else None,
        civic_progress=civics.get("civic_progress") if civics else None,
        civic_cost=civics.get("civic_cost") if civics else None,
        civics_unlocked=frozenset(civics.get("unlocked", ())) if civics else None,
        boosted_civics=frozenset(civics.get("boosted", ())) if civics else frozenset(),
        cities=tuple(_parse_city(c) for c in data.get("cities", ())),
        units=tuple(_pick(Unit, u) for u in data.get("units", ())),
        tiles=tuple(_pick(Tile, t) for t in data.get("tiles", ())),
        known_players=tuple(_pick(KnownPlayer, p) for p in data.get("known_players", ())),
        strategic_resources=dict(data.get("strategic_resources", {})),
        settle_map=_parse_settle_map(data.get("settle_map")),
    )


def _parse_settle_map(data: dict[str, Any] | None) -> SettleMap | None:
    if data is None:
        return None
    return SettleMap(
        map_width=data["map_width"], map_height=data["map_height"],
        tiles=tuple(_pick(SettleTile, t) for t in data["tiles"]),
    )
