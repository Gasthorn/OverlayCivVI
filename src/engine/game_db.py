"""Données de règles du jeu, lues dans DebugGameplay.sqlite (spec 02 §4).

La base est générée par le jeu au lancement d'une partie : elle reflète le ruleset et les mods actifs.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from engine.game_text import load_xml_names

log = logging.getLogger(__name__)

WONDER_DISTRICT = "DISTRICT_WONDER"  # quartier porté par la tuile d'une merveille

# Tables et colonnes utilisées : sert aussi à extraire la fixture de test.
TABLES: dict[str, tuple[str, ...]] = {
    "Technologies": ("TechnologyType", "Name", "Cost", "EraType"),
    "TechnologyPrereqs": ("Technology", "PrereqTech"),
    "Civics": ("CivicType", "Name", "Cost", "EraType"),
    "CivicPrereqs": ("Civic", "PrereqCivic"),
    "Boosts": (
        "TechnologyType", "CivicType", "Boost", "BoostClass", "Unit1Type", "BuildingType",
        "ImprovementType", "DistrictType", "ResourceType", "NumItems",
    ),
    "Units": ("UnitType", "Name", "PrereqTech", "PrereqCivic", "TraitType", "FormationClass", "Domain"),
    "Buildings": ("BuildingType", "Name", "PrereqTech", "PrereqCivic", "PrereqDistrict", "TraitType", "Housing"),
    "Districts": (
        "DistrictType", "Name", "PrereqTech", "PrereqCivic", "TraitType", "RequiresPopulation", "MaxPerPlayer",
        "Housing",
    ),
    "MutuallyExclusiveDistricts": ("District", "MutuallyExclusiveDistrict"),
    "Resources": ("ResourceType", "Name", "ResourceClassType", "PrereqTech"),
    "Improvements": ("ImprovementType", "Name", "PrereqTech", "PrereqCivic", "TraitType"),
    "Improvement_ValidResources": ("ImprovementType", "ResourceType"),
    "UnitReplaces": ("CivUniqueUnitType", "ReplacesUnitType"),
    "BuildingReplaces": ("CivUniqueBuildingType", "ReplacesBuildingType"),
    "DistrictReplaces": ("CivUniqueDistrictType", "ReplacesDistrictType"),
    "CivilizationTraits": ("CivilizationType", "TraitType"),
    "LeaderTraits": ("LeaderType", "TraitType"),
    "GameSpeeds": ("GameSpeedType", "CostMultiplier"),
    "Eras": ("EraType", "Name", "ChronologyIndex"),
    "Governments": ("GovernmentType", "Name"),
    "Civilizations": ("CivilizationType", "Name"),
    "Religions": ("ReligionType", "Name"),
    "District_Adjacencies": ("DistrictType", "YieldChangeId"),
    "Adjacency_YieldChanges": (
        "ID", "YieldChange", "TilesRequired", "OtherDistrictAdjacent", "AdjacentDistrict",
        "PrereqCivic", "PrereqTech", "ObsoleteCivic", "ObsoleteTech", "AdjacentWonder",
    ),
    "ExcludedAdjacencies": ("TraitType", "YieldChangeId"),
}

# Tables dont la colonne Name sert à nommer les types.
NAMED_TABLES = (
    "Technologies", "Civics", "Units", "Buildings", "Districts", "Resources", "Improvements", "Eras",
    "Governments", "Civilizations", "Religions",
)

_TYPE_PREFIX = re.compile(r"^[A-Z]+_")


@dataclass(frozen=True)
class Prereqs:
    tech: str | None
    civic: str | None
    trait: str | None


@dataclass(frozen=True)
class Boost:
    target: str          # TECH_… ou CIVIC_…
    percent: int
    boost_class: str
    unit: str | None
    building: str | None
    improvement: str | None
    district: str | None
    resource: str | None
    count: int           # au moins 1


@dataclass(frozen=True)
class DistrictAdjacencyRule:
    """Bonus d'un quartier pour des quartiers voisins (table Adjacency_YieldChanges)."""
    id: str
    yield_change: float
    tiles_required: int
    other_district: bool          # « +N par quartier voisin » (tout quartier)
    adjacent_district: str | None  # « +N à côté de tel quartier »
    prereq_civic: str | None
    prereq_tech: str | None
    obsolete_civic: str | None
    obsolete_tech: str | None
    adjacent_wonder: bool = False  # « +N par merveille voisine » (ex. Place du théâtre)

    @property
    def per_neighbor(self) -> float:
        return self.yield_change / max(self.tiles_required or 1, 1)

    def active(self, researched: set[str], civics: set[str]) -> bool:
        return (
            (self.prereq_tech is None or self.prereq_tech in researched)
            and (self.prereq_civic is None or self.prereq_civic in civics)
            and (self.obsolete_tech is None or self.obsolete_tech not in researched)
            and (self.obsolete_civic is None or self.obsolete_civic not in civics)
        )


class GameDb:
    def __init__(self, conn: sqlite3.Connection, names: dict[str, str]) -> None:
        rows = lambda table: conn.execute(f"SELECT {', '.join(TABLES[table])} FROM {table}").fetchall()  # noqa: E731

        self.tech_costs = {r[0]: r[2] for r in rows("Technologies")}
        self.civic_costs = {r[0]: r[2] for r in rows("Civics")}
        self.tech_prereqs = _group(rows("TechnologyPrereqs"))
        self.civic_prereqs = _group(rows("CivicPrereqs"))

        # Les éléments sans prérequis hors de la première ère (ère du futur de Gathering Storm)
        # sont débloqués par d'autres conditions : on ne les propose jamais.
        eras = sorted(rows("Eras"), key=lambda r: r[2])
        first_era = eras[0][0] if eras else None
        self._gated = {
            r[0] for r in rows("Technologies") if r[0] not in self.tech_prereqs and r[3] != first_era
        } | {r[0] for r in rows("Civics") if r[0] not in self.civic_prereqs and r[3] != first_era}

        self.boosts: dict[str, Boost] = {}
        for tech, civic, percent, cls, unit, building, improvement, district, resource, num in rows("Boosts"):
            target = tech or civic
            if target:
                self.boosts[target] = Boost(target, percent, cls, unit, building, improvement, district, resource, max(num or 0, 1))

        self.units = {r[0]: Prereqs(r[2], r[3], r[4]) for r in rows("Units")}
        self.naval_units = {r[0] for r in rows("Units") if r[6] == "DOMAIN_SEA"}
        self.buildings = {r[0]: Prereqs(r[2], r[3], r[5]) for r in rows("Buildings")}
        self.building_district = {r[0]: r[4] for r in rows("Buildings")}
        self.building_housing = {r[0]: r[6] or 0 for r in rows("Buildings")}
        self.districts = {r[0]: Prereqs(r[2], r[3], r[4]) for r in rows("Districts")}
        # Quartiers qui consomment un emplacement lié à la population (pas l'Aqueduc, le Barrage…).
        self.district_requires_population = {r[0]: bool(r[5]) for r in rows("Districts")}
        self.district_housing = {r[0]: r[7] or 0 for r in rows("Districts")}
        # Quartiers limités par empire (Place du gouvernement, Quartier diplomatique : 1).
        self.district_max_per_player = {r[0]: int(r[6]) for r in rows("Districts") if r[6] is not None and r[6] > 0}
        # Quartiers exclusifs dans une même ville (Complexe de divertissement / Parc aquatique).
        self.exclusive_districts = _group(rows("MutuallyExclusiveDistricts"))
        self.improvements = {r[0]: Prereqs(r[2], r[3], r[4]) for r in rows("Improvements")}
        self.resource_class = {r[0]: r[2] for r in rows("Resources")}
        self.improvements_for_resource = _group((res, imp) for imp, res in rows("Improvement_ValidResources"))

        # Remplacements uniques : générique -> versions uniques.
        self.replacements: dict[str, list[str]] = defaultdict(list)
        for table in ("UnitReplaces", "BuildingReplaces", "DistrictReplaces"):
            for unique, generic in rows(table):
                self.replacements[generic].append(unique)

        # Règles d'adjacence entre quartiers (pour évaluer une disposition hypothétique).
        changes = {r[0]: DistrictAdjacencyRule(*r) for r in rows("Adjacency_YieldChanges")}
        self.district_adjacency_rules: dict[str, list[DistrictAdjacencyRule]] = defaultdict(list)
        for district, change_id in rows("District_Adjacencies"):
            rule = changes.get(change_id)
            if rule is not None and (rule.other_district or rule.adjacent_district or rule.adjacent_wonder):
                self.district_adjacency_rules[district].append(rule)
        self.excluded_adjacencies = _group(rows("ExcludedAdjacencies"))

        self.civ_traits = _group(rows("CivilizationTraits"))
        self.leader_traits = _group(rows("LeaderTraits"))
        self.speed_multipliers = {r[0]: r[1] / 100 for r in rows("GameSpeeds")}

        self._name_tags: dict[str, str] = {}
        for table in NAMED_TABLES:
            type_column = TABLES[table][0]
            for type_, tag in conn.execute(f"SELECT {type_column}, Name FROM {table}"):
                self._name_tags[type_] = tag
        self._names = names

    # --- Chargement -----------------------------------------------------------

    @classmethod
    def load(
        cls,
        gameplay_db: Path,
        localization_db: Path | None = None,
        language: str = "fr_FR",
        game_dir: Path | None = None,
    ) -> GameDb:
        conn = _connect_read_only(gameplay_db)
        try:
            tags = {tag for table in NAMED_TABLES for (tag,) in conn.execute(f"SELECT Name FROM {table}")}
            names: dict[str, str] = {}
            fallback: dict[str, str] = {}
            if localization_db is not None and localization_db.exists():
                loc = _connect_read_only(localization_db)
                try:
                    names = load_names(loc, tags, language, fallback=None)
                    if language != "en_US":
                        fallback = load_names(loc, tags - names.keys(), "en_US", fallback=None)
                finally:
                    loc.close()
            # Traductions des extensions absentes du cache : fichiers XML de l'installation.
            if game_dir is not None and tags - names.keys():
                names |= load_xml_names(game_dir, tags - names.keys(), language)
            return cls(conn, fallback | names)
        finally:
            conn.close()

    # --- Requêtes ---------------------------------------------------------------

    def name(self, type_: str | None) -> str:
        """Nom affichable d'un type, dans la langue du jeu ; repli lisible sinon."""
        if not type_:
            return "—"
        text = self._names.get(self._name_tags.get(type_, ""))
        if text:
            return text.split("|", 1)[0]  # forme singulière (« Grenier|Greniers »)
        return _TYPE_PREFIX.sub("", type_).replace("_", " ").capitalize()

    def district_interaction(
        self, district: str, neighbor: str, traits: set[str], researched: set[str], civics: set[str]
    ) -> float:
        """Bonus d'adjacence de `district` dû au quartier voisin `neighbor` (règles de la base)."""
        excluded = {c for t in traits for c in self.excluded_adjacencies.get(t, ())}
        neighbor_variants = {neighbor, *self._generic_of(neighbor)}
        bonus = 0.0
        for rule in self.district_adjacency_rules.get(district, ()):
            if rule.id in excluded or not rule.active(researched, civics):
                continue
            if neighbor == WONDER_DISTRICT:
                # Une merveille ne compte pas comme quartier voisin, seulement pour « merveille voisine ».
                if rule.adjacent_wonder:
                    bonus += rule.per_neighbor
            elif rule.other_district or rule.adjacent_district in neighbor_variants:
                bonus += rule.per_neighbor
        return bonus

    def _generic_of(self, type_: str) -> set[str]:
        return {generic for generic, uniques in self.replacements.items() if type_ in uniques}

    def generic_district(self, district: str) -> str:
        """Type générique d'un quartier (DISTRICT_SEOWON -> DISTRICT_CAMPUS)."""
        return next(iter(self._generic_of(district)), district)

    def player_traits(self, civilization: str, leader: str) -> set[str]:
        return set(self.civ_traits.get(civilization, ())) | set(self.leader_traits.get(leader, ()))

    def available_techs(self, researched: Iterable[str]) -> list[str]:
        done = set(researched)
        return sorted((t for t in self.tech_costs if self.tech_is_available(t, done)), key=lambda t: (self.tech_costs[t], t))

    def available_civics(self, unlocked: Iterable[str]) -> list[str]:
        done = set(unlocked)
        return sorted((c for c in self.civic_costs if self.civic_is_available(c, done)), key=lambda c: (self.civic_costs[c], c))

    def is_civic(self, type_: str) -> bool:
        return type_ in self.civic_costs

    def _missing_path(self, target: str, done: set[str]) -> set[str]:
        """`target` et ses prérequis (technologies ou dogmes) pas encore acquis."""
        prereqs = self.civic_prereqs if self.is_civic(target) else self.tech_prereqs
        missing: set[str] = set()
        pending = [target]
        while pending:
            current = pending.pop()
            if current in done or current in missing:
                continue
            missing.add(current)
            pending.extend(prereqs.get(current, ()))
        return missing

    def steps_to(self, target: str, done: set[str]) -> int:
        """Nombre de technologies (ou dogmes) à acquérir pour obtenir `target`, lui compris."""
        return len(self._missing_path(target, done))

    def tech_steps(self, tech: str, researched: set[str]) -> int:
        return self.steps_to(tech, researched)

    def next_step_toward(self, target: str, done: set[str]) -> str | None:
        """Élément disponible le moins cher sur le chemin de `target` (lui-même s'il est disponible).

        `done` : technologies recherchées si `target` est une technologie, dogmes adoptés sinon.
        """
        if self.is_civic(target):
            costs, available = self.civic_costs, self.civic_is_available
        else:
            costs, available = self.tech_costs, self.tech_is_available
        steps = [t for t in self._missing_path(target, done) if available(t, done)]
        return min(steps, key=lambda t: (costs.get(t, 0), t)) if steps else None

    def tech_is_available(self, tech: str, researched: set[str]) -> bool:
        return (
            tech not in researched
            and tech not in self._gated
            and all(p in researched for p in self.tech_prereqs.get(tech, ()))
        )

    def civic_is_available(self, civic: str, unlocked: set[str]) -> bool:
        return (
            civic not in unlocked
            and civic not in self._gated
            and all(p in unlocked for p in self.civic_prereqs.get(civic, ()))
        )

    def variants(self, generic: str) -> set[str]:
        """Le type générique et ses remplacements uniques (pour compter ce que possède le joueur)."""
        return {generic, *self.replacements.get(generic, ())}

    def resolve_for_player(self, generic: str, traits: set[str]) -> str | None:
        """Version que le joueur peut réellement construire : unique si sa civ en a une, sinon générique."""
        catalog = self._catalog(generic)
        for unique in self.replacements.get(generic, ()):
            info = catalog.get(unique)
            if info is not None and info.trait in traits:
                return unique
        info = catalog.get(generic)
        if info is None or (info.trait is not None and info.trait not in traits):
            return None
        return generic

    def is_unlocked(self, type_: str, researched: set[str], unlocked_civics: set[str]) -> bool:
        info = self._catalog(type_).get(type_)
        if info is None:
            return False
        return (info.tech is None or info.tech in researched) and (info.civic is None or info.civic in unlocked_civics)

    def missing_prereq(self, type_: str, researched: set[str], unlocked_civics: set[str]) -> str | None:
        """Technologie ou dogme qui manque encore pour débloquer `type_` (None si débloqué)."""
        info = self.prereqs(type_)
        if info is None:
            return None
        if info.tech is not None and info.tech not in researched:
            return info.tech
        if info.civic is not None and info.civic not in unlocked_civics:
            return info.civic
        return None

    def prereqs(self, type_: str) -> Prereqs | None:
        return self._catalog(type_).get(type_)

    def speed_multiplier(self, game_speed: str | None) -> float:
        return self.speed_multipliers.get(game_speed or "", 1.0)

    def _catalog(self, type_: str) -> dict[str, Prereqs]:
        if type_.startswith("UNIT_"):
            return self.units
        if type_.startswith("BUILDING_"):
            return self.buildings
        if type_.startswith("DISTRICT_"):
            return self.districts
        if type_.startswith("IMPROVEMENT_"):
            return self.improvements
        # Types de mods sans préfixe standard : on cherche partout.
        for catalog in (self.units, self.buildings, self.districts, self.improvements):
            if type_ in catalog:
                return catalog
        return {}


def load_names(
    conn: sqlite3.Connection, tags: set[str], language: str, fallback: str | None = "en_US"
) -> dict[str, str]:
    """Textes localisés des tags demandés, avec repli sur `fallback` pour les textes manquants."""
    names: dict[str, str] = {}
    tag_list = sorted(tags)
    languages = [language] if fallback is None or fallback == language else [fallback, language]
    for lang in languages:  # la langue du jeu écrase le repli
        for i in range(0, len(tag_list), 500):
            chunk = tag_list[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            query = f"SELECT Tag, Text FROM LocalizedText WHERE Language = ? AND Tag IN ({placeholders})"
            names.update(conn.execute(query, (lang, *chunk)).fetchall())
    return names


class GameDbProvider:
    """Charge la base et la recharge quand le jeu la régénère (nouvelle partie, autres mods)."""

    def __init__(
        self, gameplay_db: Path, localization_db: Path | None, language: str, game_dir: Path | None = None
    ) -> None:
        self.gameplay_db = gameplay_db
        self.localization_db = localization_db
        self.language = language
        self.game_dir = game_dir
        self._db: GameDb | None = None
        self._mtime: float | None = None
        self.error: str | None = None

    def get(self) -> GameDb | None:
        try:
            mtime = self.gameplay_db.stat().st_mtime
        except FileNotFoundError:
            self.error = f"base de règles introuvable ({self.gameplay_db})"
            return self._db
        if self._db is None or mtime != self._mtime:
            try:
                self._db = GameDb.load(self.gameplay_db, self.localization_db, self.language, self.game_dir)
                self._mtime = mtime
                self.error = None
                log.info("Base de règles chargée : %s", self.gameplay_db)
            except sqlite3.Error as exc:
                self.error = f"base de règles illisible ({exc})"
                log.error("Chargement de %s impossible : %s", self.gameplay_db, exc)
        return self._db


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _group(pairs: Iterable[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for key, value in pairs:
        grouped[key].append(value)
    return {k: tuple(v) for k, v in grouped.items()}
