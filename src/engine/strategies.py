"""Scores de stratégie heuristiques (spec 02 §6).

Score = (somme pondérée des facteurs additifs) × (produit des multiplicateurs).
Chaque facteur vaut entre 0 et 1 ; les poids additifs d'une stratégie somment à 1. Un multiplicateur
de valeur v applique un coefficient 0.3 + 0.7 × v : il représente une condition sans laquelle la
stratégie perd l'essentiel de son intérêt (ex. le timing d'un rush). Les tours sont normalisés à la
vitesse Standard (spec 02 §4).

Les facteurs « emplacement » utilisent l'adjacence calculée par le jeu (`cities[].district_sites`)
quand elle est exportée, et une estimation à partir des tuiles sinon.

Pondérations (à garder synchronisées avec la spec et les tests) :

- cavalry_rush        : chevaux 0.40, Équitation 0.25, voisin 0.20, unique 0.15 ; × timing antique
- medieval_army       : fer 0.25, Étriers 0.20, voisin 0.20, campements 0.15, unique 0.20 ; × timing médiéval
- commercial_hub_rush : Monnaie 0.25, emplacement 0.25, or 0.20, côtes 0.10, plateformes 0.10, unique 0.10
- science_campus      : emplacement 0.30, Écriture 0.20, science 0.20, campus 0.20, unique 0.10
- culture_victory     : culture 0.30, emplacement 0.20, Art dramatique 0.15, théâtres 0.15, merveilles 0.10, unique 0.10
- religious_victory   : foi 0.25, religion fondée 0.20, emplacement 0.20, lieux saints 0.15, Astrologie 0.10, unique 0.10
- naval_warfare       : emplacement 0.25, Navigation céleste 0.20, ressources marines 0.15, voisin 0.15,
                        ports 0.10, unique 0.15 ; × villes côtières
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from engine.game_db import GameDb
from engine.state import GameState, KnownPlayer
from engine.strategy_focus import best_site
from engine.text import de, plural, signed

MULTIPLIER_FLOOR = 0.3
WATER_TERRAINS = frozenset({"TERRAIN_COAST", "TERRAIN_OCEAN"})


@dataclass(frozen=True)
class Factor:
    weight: float
    value: float  # 0..1
    label: str
    multiplier: bool = False

    @property
    def contribution(self) -> float:
        return self.weight * self.value

    @property
    def coefficient(self) -> float:
        return MULTIPLIER_FLOOR + (1 - MULTIPLIER_FLOOR) * self.value


@dataclass(frozen=True)
class _Context:
    state: GameState
    db: GameDb
    researched: set[str]
    civics: set[str]
    traits: set[str]
    turn: float           # tour normalisé à la vitesse Standard
    cities: int


def score_strategies(state: GameState, db: GameDb) -> list[dict[str, Any]]:
    """Messages `strategies` (spec 04), triés par score décroissant."""
    ctx = _Context(
        state=state,
        db=db,
        researched=set(state.researched),
        civics=set(state.civics_unlocked or ()),
        traits=db.player_traits(state.civilization, state.leader),
        turn=state.turn / db.speed_multiplier(state.game_speed),
        cities=max(1, len(state.cities)),
    )
    results = []
    for strategy_id, label, icon, factors_fn in STRATEGIES:
        factors = factors_fn(ctx)
        additive = [f for f in factors if not f.multiplier]
        multipliers = [f for f in factors if f.multiplier]
        score = sum(f.contribution for f in additive) * math.prod(m.coefficient for m in multipliers)

        shown = sorted((f for f in additive if f.value > 0), key=lambda f: -f.contribution)
        # Un multiplicateur pénalisant est la première explication du score ; sinon il vient en dernier.
        penalties = [m for m in multipliers if m.value < 0.5]
        bonuses = [m for m in multipliers if m.value >= 0.5]
        results.append({
            "id": strategy_id,
            "label": label,
            "icon": icon,
            "score": round(min(1.0, max(0.0, score)), 2),
            "factors": [f.label for f in penalties + shown + bonuses],
        })
    return sorted(results, key=lambda s: -s["score"])


# --- Facteurs communs ---------------------------------------------------------

def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _progress(ctx: _Context, target: str, weight: float) -> Factor:
    """Progression vers une technologie ou un dogme clé."""
    is_civic = ctx.db.is_civic(target)
    done = ctx.civics if is_civic else ctx.researched
    boosted = target in (ctx.state.boosted_civics if is_civic else ctx.state.boosted_techs)
    name = ctx.db.name(target)
    if target in done:
        return Factor(weight, 1.0, f"{name} {'adopté' if is_civic else 'recherchée'}")
    if is_civic and ctx.state.civics_unlocked is None:
        return Factor(weight, 0.0, "")
    steps = ctx.db.steps_to(target, done)
    value = _clamp(1 - steps / 4)
    if boosted:
        value = min(0.95, value + 0.15)
    if steps == 1:
        label = f"{name} disponible" + ((" (Inspiration obtenue)" if is_civic else " (Eurêka obtenu)") if boosted else "")
    else:
        label = f"À {steps} {'dogmes' if is_civic else 'technologies'} {de(name)}"
    return Factor(weight, value, label)


def _unique_bonus(ctx: _Context, generics: tuple[str, ...], weight: float) -> Factor:
    for generic in generics:
        resolved = ctx.db.resolve_for_player(generic, ctx.traits)
        if resolved is not None and resolved != generic:
            return Factor(weight, 1.0, f"Bonus unique : {ctx.db.name(resolved)}")
    return Factor(weight, 0.0, "")


def _district_ratio(ctx: _Context, district: str, weight: float, label: str) -> Factor:
    variants = ctx.db.variants(district)
    count = sum(bool(variants & c.districts) for c in ctx.state.cities)
    return Factor(weight, count / ctx.cities, f"{count}/{len(ctx.state.cities)} villes avec {label}")


def _site_factor(ctx: _Context, district: str, weight: float, fallback: Callable[[], Factor]) -> Factor:
    """Adjacence des meilleurs emplacements libres (calculée par le jeu), sinon estimation `fallback`."""
    variants = ctx.db.variants(district)
    candidates = [c for c in ctx.state.cities if not variants & c.districts]
    if not any(c.district_sites is not None for c in candidates):
        return fallback()
    sites = sorted(
        ((site, city) for city in candidates if (site := best_site(city, ctx.db, district, ctx.traits)) is not None),
        key=lambda sc: -sc[0].adjacency,
    )
    if not sites:
        return Factor(weight, 0.0, "")
    top = [site.adjacency for site, _ in sites[:2]]
    best, city = sites[0]
    name = ctx.db.name(ctx.db.resolve_for_player(district, ctx.traits) or district)
    return Factor(
        weight, _clamp(sum(top) / len(top) / 3),
        f"Meilleur emplacement de {name} : {signed(best.adjacency)} à {city.name}",
    )


def _workable_tiles(ctx: _Context):
    return [t for t in ctx.state.tiles if t.owner != "other"]


def _player_name(ctx: _Context, player: KnownPlayer) -> str:
    return player.name or ctx.db.name(player.civilization)


def _neighbor_factor(ctx: _Context, weight: float) -> Factor:
    neighbors = ctx.state.known_players
    at_war = [p for p in neighbors if p.at_war]
    target = at_war or neighbors
    label = ("En guerre contre " if at_war else "Voisin rencontré : ") + ", ".join(
        _player_name(ctx, p) for p in target[:2]
    )
    return Factor(weight, 1.0 if neighbors else 0.0, label)


def _resource_factor(
    ctx: _Context, resource: str, tile_words: tuple[str, str], stock_words: tuple[str, str], weight: float
) -> Factor:
    """Ressource stratégique : gisements près des villes et réserve. `*_words` : (singulier, pluriel)."""
    tiles = sum(t.resource == resource for t in _workable_tiles(ctx))
    stock = ctx.state.strategic_resources.get(resource, 0)
    labels = []
    if tiles:
        labels.append(f"{plural(tiles, *tile_words)} près de vos villes")
    if stock:
        labels.append(f"{plural(stock, *stock_words)} en réserve")
    return Factor(weight, _clamp(tiles / 2 + stock / 20), ", ".join(labels))


def _window(ctx: _Context, start: float, peak_start: float, peak_end: float, end: float, era: str) -> Factor:
    """Multiplicateur de timing : 0 avant `start`, 1 entre `peak_start` et `peak_end`, 0 après `end`."""
    t = ctx.turn
    if t < peak_start:
        value = _clamp((t - start) / (peak_start - start))
        text = f"fenêtre {era.lower()} qui s'ouvre" if value >= 0.5 else f"{era} encore lointain"
    elif t <= peak_end:
        value, text = 1.0, f"fenêtre {era.lower()} favorable"
    else:
        value, text = _clamp((end - t) / (end - peak_end)), f"fenêtre {era.lower()} qui se referme"
    return Factor(1.0, value, f"Tour {ctx.state.turn} : {text}", multiplier=True)


# --- Stratégies -----------------------------------------------------------------

def _cavalry_rush(ctx: _Context) -> list[Factor]:
    timing = _clamp((90 - ctx.turn) / 50)
    window = "favorable" if timing >= 0.5 else "qui se referme"
    return [
        _resource_factor(ctx, "RESOURCE_HORSES", ("cheval", "chevaux"), ("cheval", "chevaux"), 0.40),
        _progress(ctx, "TECH_HORSEBACK_RIDING", 0.25),
        _neighbor_factor(ctx, 0.20),
        _unique_bonus(ctx, ("UNIT_HORSEMAN", "UNIT_HEAVY_CHARIOT", "UNIT_KNIGHT", "UNIT_COURSER"), 0.15),
        Factor(1.0, timing, f"Tour {ctx.state.turn} : fenêtre d'attaque {window}", multiplier=True),
    ]


def _medieval_army(ctx: _Context) -> list[Factor]:
    return [
        _resource_factor(
            ctx, "RESOURCE_IRON", ("gisement de fer", "gisements de fer"), ("unité de fer", "unités de fer"), 0.25,
        ),
        _progress(ctx, "TECH_STIRRUPS", 0.20),
        _neighbor_factor(ctx, 0.20),
        _district_ratio(ctx, "DISTRICT_ENCAMPMENT", 0.15, "campement"),
        _unique_bonus(ctx, ("UNIT_KNIGHT", "UNIT_MAN_AT_ARMS", "UNIT_CROSSBOWMAN", "UNIT_SWORDSMAN", "DISTRICT_ENCAMPMENT"), 0.20),
        _window(ctx, start=30, peak_start=70, peak_end=140, end=200, era="Moyen Âge"),
    ]


def _commercial_hub_rush(ctx: _Context) -> list[Factor]:
    tiles = _workable_tiles(ctx)
    river_tiles = sum(t.river for t in tiles)
    coastal = sum(bool(c.coastal) for c in ctx.state.cities)
    gold = ctx.state.yields.gold_per_turn or 0
    return [
        _progress(ctx, "TECH_CURRENCY", 0.25),
        _site_factor(ctx, "DISTRICT_COMMERCIAL_HUB", 0.25, lambda: Factor(
            0.25, _clamp(river_tiles / (3 * ctx.cities)), f"{plural(river_tiles, 'tuile')} de rivière près de vos villes",
        )),
        Factor(0.20, _clamp(gold / (3 + 0.25 * ctx.turn)), f"Or : {signed(gold)}/tour"),
        Factor(0.10, coastal / ctx.cities, f"{plural(coastal, 'ville côtière', 'villes côtières')} (port adjacent)"),
        _district_ratio(ctx, "DISTRICT_COMMERCIAL_HUB", 0.10, "plateforme commerciale"),
        _unique_bonus(ctx, ("DISTRICT_COMMERCIAL_HUB", "BUILDING_MARKET", "BUILDING_BANK"), 0.10),
    ]


def _science_campus(ctx: _Context) -> list[Factor]:
    tiles = _workable_tiles(ctx)
    mountains = sum(t.terrain.endswith("_MOUNTAIN") for t in tiles)
    jungles = sum(t.feature == "FEATURE_JUNGLE" for t in tiles)
    science = ctx.state.yields.science_per_turn or 0
    return [
        _site_factor(ctx, "DISTRICT_CAMPUS", 0.30, lambda: Factor(
            0.30, _clamp((mountains + 0.5 * jungles) / (2 * ctx.cities)),
            f"{plural(mountains, 'montagne')} et {plural(jungles, 'jungle')} près de vos villes",
        )),
        _progress(ctx, "TECH_WRITING", 0.20),
        Factor(0.20, _clamp(science / (2 + 0.5 * ctx.turn)), f"Science : {signed(science)}/tour"),
        _district_ratio(ctx, "DISTRICT_CAMPUS", 0.20, "campus"),
        _unique_bonus(ctx, ("DISTRICT_CAMPUS", "BUILDING_LIBRARY", "BUILDING_UNIVERSITY"), 0.10),
    ]


def _culture_victory(ctx: _Context) -> list[Factor]:
    culture = ctx.state.yields.culture_per_turn or 0
    wonders = sum("DISTRICT_WONDER" in c.districts for c in ctx.state.cities)
    return [
        Factor(0.30, _clamp(culture / (2 + 0.4 * ctx.turn)), f"Culture : {signed(culture)}/tour"),
        _site_factor(ctx, "DISTRICT_THEATER", 0.20, lambda: Factor(0.20, 0.0, "")),
        _progress(ctx, "CIVIC_DRAMA_POETRY", 0.15),
        _district_ratio(ctx, "DISTRICT_THEATER", 0.15, "théâtre"),
        Factor(0.10, _clamp(wonders / 3), f"{plural(wonders, 'ville')} avec merveille"),
        _unique_bonus(ctx, ("DISTRICT_THEATER", "BUILDING_AMPHITHEATER", "BUILDING_MUSEUM_ART"), 0.10),
    ]


def _religious_victory(ctx: _Context) -> list[Factor]:
    faith = ctx.state.yields.faith_per_turn or 0
    tiles = _workable_tiles(ctx)
    mountains = sum(t.terrain.endswith("_MOUNTAIN") for t in tiles)
    forests = sum(t.feature == "FEATURE_FOREST" for t in tiles)
    if ctx.state.religion:
        religion = Factor(0.20, 1.0, f"Religion fondée : {ctx.db.name(ctx.state.religion)}")
    else:
        # Sans religion, la fenêtre pour en fonder une se referme vite.
        religion = Factor(0.20, _clamp((80 - ctx.turn) / 80) * 0.5, "Pas encore de religion fondée")
    return [
        Factor(0.25, _clamp(faith / (1 + 0.25 * ctx.turn)), f"Foi : {signed(faith)}/tour"),
        religion,
        _site_factor(ctx, "DISTRICT_HOLY_SITE", 0.20, lambda: Factor(
            0.20, _clamp((mountains + 0.5 * forests) / (2 * ctx.cities)),
            f"{plural(mountains, 'montagne')} et {plural(forests, 'forêt')} près de vos villes",
        )),
        _district_ratio(ctx, "DISTRICT_HOLY_SITE", 0.15, "lieu saint"),
        _progress(ctx, "TECH_ASTROLOGY", 0.10),
        _unique_bonus(ctx, ("DISTRICT_HOLY_SITE", "BUILDING_TEMPLE", "UNIT_MISSIONARY"), 0.10),
    ]


def _naval_warfare(ctx: _Context) -> list[Factor]:
    coastal = sum(bool(c.coastal) for c in ctx.state.cities)
    # `cities[].coastal` absent (export antérieur au champ) : on ne pénalise pas.
    coast_known = any(c.coastal is not None for c in ctx.state.cities)
    sea_resources = sum(t.resource is not None and t.terrain in WATER_TERRAINS for t in _workable_tiles(ctx))
    coast_label = f"{plural(coastal, 'ville côtière', 'villes côtières')} sur {len(ctx.state.cities)}"
    factors = [
        _site_factor(ctx, "DISTRICT_HARBOR", 0.25, lambda: Factor(
            0.25, coastal / ctx.cities, coast_label if coastal else "",
        )),
        _progress(ctx, "TECH_CELESTIAL_NAVIGATION", 0.20),
        Factor(0.15, _clamp(sea_resources / (2 * ctx.cities)),
               f"{plural(sea_resources, 'ressource marine', 'ressources marines')} près de vos villes"),
        _neighbor_factor(ctx, 0.15),
        _district_ratio(ctx, "DISTRICT_HARBOR", 0.10, "port"),
        _unique_bonus(ctx, ("UNIT_GALLEY", "UNIT_QUADRIREME", "UNIT_FRIGATE", "UNIT_PRIVATEER", "DISTRICT_HARBOR"), 0.15),
    ]
    if coast_known:
        # Sans côte, pas de flotte : condition indispensable.
        factors.append(Factor(1.0, coastal / ctx.cities, coast_label if coastal else "Aucune ville côtière", multiplier=True))
    return factors


STRATEGIES: tuple[tuple[str, str, str, Callable[[_Context], list[Factor]]], ...] = (
    ("cavalry_rush", "Rush Cavalerie", "horse", _cavalry_rush),
    ("medieval_army", "Armée médiévale", "shield", _medieval_army),
    ("commercial_hub_rush", "Plateformes commerciales", "coin", _commercial_hub_rush),
    ("science_campus", "Victoire scientifique", "flask", _science_campus),
    ("culture_victory", "Victoire culturelle", "scroll", _culture_victory),
    ("religious_victory", "Victoire religieuse", "dove", _religious_victory),
    ("naval_warfare", "Bataille navale", "anchor", _naval_warfare),
)
