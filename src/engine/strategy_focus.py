"""Actions de focus pour la stratégie suivie par le joueur (spec 02 §6.5).

Chaque stratégie est décrite par un plan déclaratif ; les actions qui en découlent portent
`strategy = <id>` et des priorités de 70 à 78, au-dessus des actions ordinaires rétrogradées
par run_rules mais sous les actions urgentes (≥ 80).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.game_db import GameDb
from engine.rules import Action
from engine.state import City, DistrictSite, GameState
from engine.text import plural


@dataclass(frozen=True)
class StrategyPlan:
    label: str
    # Technologies ou dogmes clés, dans l'ordre, avec l'élément qu'ils débloquent (pour le texte).
    key_steps: tuple[tuple[str, str], ...]
    # Quartier à bâtir, puis chaîne de bâtiments ; chaque maillon liste des alternatives
    # (ex. Caserne ou Écurie, exclusives dans le jeu) : il est acquis si l'une est construite.
    district: str | None = None
    buildings: tuple[tuple[str, ...], ...] = ()
    # Unités (génériques, de la plus avancée à la plus ancienne) et effectif visé.
    units: tuple[str, ...] = ()
    unit_target: int = 0
    unit_label: str = "unités"
    units_require_religion: bool = False
    # (ressource, aménagement) à exploiter sur les tuiles du joueur.
    improvements: tuple[tuple[str, str], ...] = ()
    # Nombre de villes visé pendant la phase d'expansion (colons).
    city_target: int = 6
    # Merveilles clés, par ordre de priorité (la première disponible est proposée, `wonders.py`).
    wonders: tuple[str, ...] = ()
    # Quartier et unités réservés aux villes côtières (stratégie navale).
    coastal_only: bool = False


PLANS: dict[str, StrategyPlan] = {
    "cavalry_rush": StrategyPlan(
        label="Rush Cavalerie",
        key_steps=(("TECH_HORSEBACK_RIDING", "UNIT_HORSEMAN"), ("TECH_STIRRUPS", "UNIT_KNIGHT")),
        district="DISTRICT_ENCAMPMENT",
        buildings=(("BUILDING_STABLE", "BUILDING_BARRACKS"),),
        units=("UNIT_KNIGHT", "UNIT_COURSER", "UNIT_HORSEMAN", "UNIT_HEAVY_CHARIOT"),
        unit_target=4,
        unit_label="unités de cavalerie",
        improvements=(("RESOURCE_HORSES", "IMPROVEMENT_PASTURE"),),
        city_target=4,  # rush : peu de villes, la production va à l'armée
        wonders=("BUILDING_TERRACOTTA_ARMY",),
    ),
    "medieval_army": StrategyPlan(
        label="Armée médiévale",
        key_steps=(
            ("TECH_STIRRUPS", "UNIT_KNIGHT"),
            ("TECH_MILITARY_TACTICS", "UNIT_MAN_AT_ARMS"),
            ("TECH_MILITARY_ENGINEERING", "BUILDING_ARMORY"),
        ),
        district="DISTRICT_ENCAMPMENT",
        buildings=(("BUILDING_BARRACKS", "BUILDING_STABLE"), ("BUILDING_ARMORY",)),
        units=("UNIT_KNIGHT", "UNIT_MAN_AT_ARMS", "UNIT_CROSSBOWMAN", "UNIT_SWORDSMAN"),
        unit_target=6,
        unit_label="unités médiévales",
        improvements=(("RESOURCE_IRON", "IMPROVEMENT_MINE"),),
        wonders=("BUILDING_TERRACOTTA_ARMY", "BUILDING_ALHAMBRA", "BUILDING_STATUE_OF_ZEUS"),
    ),
    "commercial_hub_rush": StrategyPlan(
        label="Plateformes commerciales",
        key_steps=(("TECH_CURRENCY", "DISTRICT_COMMERCIAL_HUB"), ("TECH_BANKING", "BUILDING_BANK")),
        district="DISTRICT_COMMERCIAL_HUB",
        buildings=(("BUILDING_MARKET",), ("BUILDING_BANK",)),
        wonders=("BUILDING_COLOSSUS", "BUILDING_PETRA", "BUILDING_GREAT_ZIMBABWE", "BUILDING_BIG_BEN"),
    ),
    "science_campus": StrategyPlan(
        label="Victoire scientifique",
        key_steps=(("TECH_WRITING", "DISTRICT_CAMPUS"), ("TECH_EDUCATION", "BUILDING_UNIVERSITY")),
        district="DISTRICT_CAMPUS",
        buildings=(("BUILDING_LIBRARY",), ("BUILDING_UNIVERSITY",)),
        wonders=("BUILDING_GREAT_LIBRARY", "BUILDING_UNIVERSITY_SANKORE", "BUILDING_OXFORD_UNIVERSITY"),
    ),
    "culture_victory": StrategyPlan(
        label="Victoire culturelle",
        key_steps=(("CIVIC_DRAMA_POETRY", "DISTRICT_THEATER"), ("CIVIC_HUMANISM", "BUILDING_MUSEUM_ART")),
        district="DISTRICT_THEATER",
        buildings=(("BUILDING_AMPHITHEATER",), ("BUILDING_MUSEUM_ART", "BUILDING_MUSEUM_ARTIFACT")),
        wonders=(
            "BUILDING_ORACLE", "BUILDING_COLOSSEUM", "BUILDING_FORBIDDEN_CITY", "BUILDING_BOLSHOI_THEATRE",
            "BUILDING_HERMITAGE", "BUILDING_CRISTO_REDENTOR", "BUILDING_BROADWAY", "BUILDING_SYDNEY_OPERA_HOUSE",
        ),
    ),
    "religious_victory": StrategyPlan(
        label="Victoire religieuse",
        key_steps=(("TECH_ASTROLOGY", "DISTRICT_HOLY_SITE"), ("CIVIC_THEOLOGY", "BUILDING_TEMPLE")),
        district="DISTRICT_HOLY_SITE",
        buildings=(("BUILDING_SHRINE",), ("BUILDING_TEMPLE",)),
        units=("UNIT_APOSTLE", "UNIT_MISSIONARY"),
        unit_target=3,
        unit_label="unités religieuses",
        units_require_religion=True,
        wonders=(
            "BUILDING_STONEHENGE", "BUILDING_MAHABODHI_TEMPLE", "BUILDING_HAGIA_SOPHIA", "BUILDING_KOTOKU_IN",
            "BUILDING_MEENAKSHI_TEMPLE", "BUILDING_MONT_ST_MICHEL",
        ),
    ),
    "naval_warfare": StrategyPlan(
        label="Bataille navale",
        key_steps=(
            ("TECH_SAILING", "UNIT_GALLEY"),
            ("TECH_SHIPBUILDING", "UNIT_QUADRIREME"),
            ("TECH_CELESTIAL_NAVIGATION", "DISTRICT_HARBOR"),
            ("TECH_SQUARE_RIGGING", "UNIT_FRIGATE"),
        ),
        district="DISTRICT_HARBOR",
        buildings=(("BUILDING_LIGHTHOUSE",), ("BUILDING_SHIPYARD",)),
        units=("UNIT_FRIGATE", "UNIT_QUADRIREME", "UNIT_GALLEY"),
        unit_target=4,
        unit_label="navires de guerre",
        wonders=("BUILDING_GREAT_LIGHTHOUSE", "BUILDING_COLOSSUS", "BUILDING_VENETIAN_ARSENAL"),
        coastal_only=True,
    ),
}

MAX_DISTRICT_CITIES = 2  # villes proposées pour le quartier

# Expansion : colons proposés jusqu'à la fin du Moyen Âge, une ville à la fois.
EXPANSION_ERAS = frozenset({"ERA_ANCIENT", "ERA_CLASSICAL", "ERA_MEDIEVAL"})
SETTLER = "UNIT_SETTLER"
BUILDER = "UNIT_BUILDER"
BUILDER_CHARGES = 3  # aménagements par bâtisseur (sans bonus)

# Quartiers hors quota de population (`Districts.RequiresPopulation = 0`) proposés selon les besoins
# de la ville ; le type générique couvre les versions uniques (Thermes, Mbanza…).
AQUEDUCT = "DISTRICT_AQUEDUCT"
NEIGHBORHOOD = "DISTRICT_NEIGHBORHOOD"
DAM = "DISTRICT_DAM"


def focus_actions(state: GameState, db: GameDb, strategy_id: str) -> list[Action]:
    plan = PLANS.get(strategy_id)
    if plan is None:
        return []
    ctx = _Focus(state, db, strategy_id, plan)
    return (
        ctx.research() + ctx.districts() + ctx.wonders() + ctx.support_districts() + ctx.buildings() + ctx.units()
        + ctx.settlers() + ctx.builders() + ctx.improvements()
    )


def best_site(city: City, db: GameDb, district: str, traits: set[str]) -> DistrictSite | None:
    """Meilleur emplacement exporté pour la version du quartier que le joueur peut construire.

    Le jeu déclare aussi valides les quartiers uniques d'autres civilisations : on les ignore.
    """
    if not city.district_sites:
        return None
    own = db.resolve_for_player(district, traits)
    return city.district_sites.get(own) if own else None


class _Focus:
    def __init__(self, state: GameState, db: GameDb, strategy_id: str, plan: StrategyPlan) -> None:
        self.state, self.db, self.strategy_id, self.plan = state, db, strategy_id, plan
        self.researched = set(state.researched)
        self.civics = set(state.civics_unlocked or ())
        self.traits = db.player_traits(state.civilization, state.leader)

    def _action(self, key: str, category: str, title: str, reason: str, priority: int, **target) -> Action:
        return Action(
            id=f"focus:{self.strategy_id}:{key}", category=category, title=title,
            reason=f"{self.plan.label} : {reason}", priority=priority, strategy=self.strategy_id, **target,
        )

    def _buildable(self, generic: str) -> str | None:
        item = self.db.resolve_for_player(generic, self.traits)
        if item is None or not self.db.is_unlocked(item, self.researched, self.civics):
            return None
        return item

    def _producing(self, city: City, generic: str) -> bool:
        return city.current_production in self.db.variants(generic)

    # --- Recherche et dogmes ------------------------------------------------------

    def research(self) -> list[Action]:
        """Au plus une technologie et un dogme : le prochain pas vers la première clé manquante de chaque arbre."""
        actions: list[Action] = []
        handled: set[str] = set()
        for key, unlocks in self.plan.key_steps:
            is_civic = self.db.is_civic(key)
            tree = "civic" if is_civic else "research"
            done = self.civics if is_civic else self.researched
            if tree in handled or key in done:
                continue
            if is_civic and self.state.civics_unlocked is None:
                continue  # dogmes inconnus (section absente)
            handled.add(tree)
            step = self.db.next_step_toward(key, done)
            current = self.state.current_civic if is_civic else self.state.current_research
            if step is None or step == current:
                continue
            unlocked = self.db.name(self.db.resolve_for_player(unlocks, self.traits) or unlocks)
            reason = f"débloque {unlocked}" if step == key else f"en route vers {self.db.name(key)} ({unlocked})"
            verb = "Adopter" if is_civic else "Rechercher"
            actions.append(self._action(
                f"{tree}:{step}", tree, f"{verb} {self.db.name(step)}", reason, 78, target_type=step,
            ))
        return actions

    # --- Quartiers et bâtiments ----------------------------------------------------

    def districts(self) -> list[Action]:
        if self.plan.district is None:
            return []
        district = self._buildable(self.plan.district)
        if district is None:
            return []
        variants = self.db.variants(self.plan.district)
        candidates = [
            c for c in self.state.cities
            if not variants & c.districts and not self._producing(c, self.plan.district)
            and not (self.plan.coastal_only and c.coastal is False)
        ]
        name = self.db.name(district)

        # Emplacements calculés par le jeu (spec 01) : une ville sans emplacement valide est écartée,
        # les autres sont classées par adjacence. Sans données, ou si aucun emplacement n'a de bonus
        # (ex. Campement, sans adjacence dans le jeu) : classement par population.
        sites: dict[int, DistrictSite] = {}
        if any(c.district_sites is not None for c in candidates):
            for city in candidates:
                site = best_site(city, self.db, self.plan.district, self.traits)
                if site is not None:
                    sites[city.city_id] = site
            candidates = [c for c in candidates if c.city_id in sites]

        if any(s.adjacency for s in sites.values()):
            chosen = sorted(candidates, key=lambda c: (-sites[c.city_id].adjacency, -c.population, c.city_id))
            reasons = [
                f"meilleur emplacement, adjacence {sites[c.city_id].adjacency:+g}"
                if sites[c.city_id].adjacency else "emplacement sans bonus d'adjacence"
                for c in chosen
            ]
        else:
            chosen = sorted(candidates, key=lambda c: (-c.population, c.city_id))
            reasons = [f"ville sans {name} ({plural(c.population, 'habitant')})" for c in chosen]

        return [
            self._action(
                f"district:{city.city_id}", "production", f"Construire {name} à {city.name}", reason,
                77 - rank, target_type=district, city_id=city.city_id,
            )
            for rank, (city, reason) in enumerate(list(zip(chosen, reasons))[:MAX_DISTRICT_CITIES])
        ]

    def wonders(self) -> list[Action]:
        """Première merveille du plan disponible, dans la ville et sur la tuile choisies par `wonders.py`."""
        from engine.wonders import wonder_pick, wonder_reason

        pick = wonder_pick(self.state, self.db, self.strategy_id)
        if pick is None:
            return []
        city = next(c for c in self.state.cities if c.city_id == pick.city_id)
        return [self._action(
            "wonder", "production", f"Construire {self.db.name(pick.wonder)} à {city.name}",
            wonder_reason(pick), 74, target_type=pick.wonder, city_id=city.city_id,
        )]

    def support_districts(self) -> list[Action]:
        """Quartiers hors quota (Aqueduc, Quartier résidentiel, Barrage…) : au plus un par ville, le
        plus utile. Ils ne prennent pas d'emplacement aux quartiers de la stratégie."""
        actions = []
        for city in self.state.cities:
            options = [a for a in (self._aqueduct(city), self._neighborhood(city), self._dam(city)) if a]
            if options:
                actions.append(max(options, key=lambda a: a.priority))
        return actions

    def _support(self, city: City, generic: str) -> str | None:
        """Version du joueur, débloquée, hors quota, absente de la ville et avec un emplacement valide
        (quand les emplacements sont connus)."""
        district = self._buildable(generic)
        if district is None or self.db.district_requires_population.get(district, True):
            return None
        if self.db.variants(generic) & city.districts or self._producing(city, generic):
            return None
        if city.district_sites is not None and best_site(city, self.db, generic, self.traits) is None:
            return None
        return district

    def _housing_short(self, city: City) -> bool:
        return city.housing is not None and city.population >= city.housing - 1

    def _housing_text(self, district: str) -> str:
        housing = self.db.district_housing.get(district, 0)
        return f" (+{housing:g} logement{'s' if housing > 1 else ''})" if housing else ""

    def _support_action(self, city: City, district: str, reason: str, priority: int) -> Action:
        return self._action(
            f"support:{city.city_id}", "production", f"Construire {self.db.name(district)} à {city.name}",
            f"{reason} · hors quota de quartiers", priority, target_type=district, city_id=city.city_id,
        )

    def _aqueduct(self, city: City) -> Action | None:
        district = self._support(city, AQUEDUCT)
        if district is None or not self._housing_short(city):
            return None
        return self._support_action(
            city, district, f"logement saturé ({city.population}/{city.housing:g}){self._housing_text(district)}", 74,
        )

    def _neighborhood(self, city: City) -> Action | None:
        district = self._support(city, NEIGHBORHOOD)
        if district is None or not self._housing_short(city):
            return None
        # Après l'Aqueduc, sauf si la ville ne peut pas en avoir (pas d'eau douce ni de montagne).
        aqueduct = self._support(city, AQUEDUCT)
        if aqueduct is not None:
            return None
        return self._support_action(
            city, district, f"logement saturé ({city.population}/{city.housing:g}){self._housing_text(district)}", 73,
        )

    def _dam(self, city: City) -> Action | None:
        # Le Barrage n'est valide que sur une plaine inondable : l'emplacement doit être connu.
        district = self._support(city, DAM)
        if district is None or city.district_sites is None:
            return None
        return self._support_action(
            city, district, f"protège la plaine inondable des crues{self._housing_text(district)}", 71,
        )

    def buildings(self) -> list[Action]:
        actions = []
        district_variants = self.db.variants(self.plan.district) if self.plan.district else set()
        district_name = self.db.name(self.plan.district) if self.plan.district else "la stratégie"
        for city in self.state.cities:
            if district_variants and not district_variants & city.districts:
                continue
            for alternatives in self.plan.buildings:
                if any(self.db.variants(b) & city.buildings for b in alternatives):
                    continue  # maillon acquis : on passe au suivant de la chaîne
                if any(self._producing(city, b) for b in alternatives):
                    break
                building = next((b for b in map(self._buildable, alternatives) if b is not None), None)
                if building is not None:
                    actions.append(self._action(
                        f"building:{city.city_id}", "production", f"Construire {self.db.name(building)} à {city.name}",
                        f"renforce {district_name}", 72, target_type=building, city_id=city.city_id,
                    ))
                break  # un seul bâtiment par ville : le premier maillon manquant
        return actions

    # --- Unités et aménagements ------------------------------------------------------

    def units(self) -> list[Action]:
        if not self.plan.units:
            return []
        if self.plan.units_require_religion and not self.state.religion:
            return []
        if self.plan.coastal_only and self.state.cities and all(c.coastal is False for c in self.state.cities):
            return []
        family = set().union(*(self.db.variants(u) for u in self.plan.units))
        owned = sum(u.type in family for u in self.state.units)
        missing = self.plan.unit_target - owned
        if missing <= 0:
            return []
        unit = next((u for u in map(self._buildable, self.plan.units) if u is not None), None)
        if unit is None:
            return []
        count = f"{missing} × " if missing > 1 else ""
        return [self._action(
            "units", "production", f"Produire {count}{self.db.name(unit)}",
            f"{owned}/{self.plan.unit_target} {self.plan.unit_label}", 70, target_type=unit,
        )]

    def _in_progress(self, generic: str) -> int:
        """Unités possédées + villes qui les produisent."""
        variants = self.db.variants(generic)
        return sum(u.type in variants for u in self.state.units) + sum(
            self._producing(c, generic) for c in self.state.cities
        )

    def _producer(self, generic: str, min_population: int = 1) -> City | None:
        """Ville la plus peuplée (indicateur de production) qui ne produit pas déjà cette unité."""
        cities = [
            c for c in self.state.cities if c.population >= min_population and not self._producing(c, generic)
        ]
        return max(cities, key=lambda c: (c.population, -c.city_id), default=None)

    def settlers(self) -> list[Action]:
        """Phase d'expansion : un colon à la fois tant que l'objectif de villes n'est pas atteint."""
        if self.state.era not in EXPANSION_ERAS or not self.state.cities:
            return []
        settler = self._buildable(SETTLER)
        planned = len(self.state.cities) + self._in_progress(SETTLER)
        if settler is None or planned >= self.plan.city_target or self._in_progress(SETTLER):
            return []
        city = self._producer(SETTLER, min_population=2)  # le colon coûte 1 habitant
        if city is None:
            return []
        return [self._action(
            "settlers", "production", f"Produire {self.db.name(settler)} à {city.name}",
            f"{len(self.state.cities)}/{self.plan.city_target} villes : s'étendre tôt multiplie la production",
            75, target_type=settler, city_id=city.city_id,
        )]

    def builders(self) -> list[Action]:
        """Bâtisseurs : assez de charges pour les ressources non aménagées, au plus un par ville."""
        builder = self._buildable(BUILDER)
        if builder is None:
            return []
        todo = sum(
            t.owner == "self" and t.resource is not None and t.improvement is None and self._improvable(t.resource)
            for t in self.state.tiles
        )
        have = self._in_progress(BUILDER)
        wanted = min(len(self.state.cities), -(-todo // BUILDER_CHARGES))
        if have >= wanted:
            return []
        city = self._producer(BUILDER)
        if city is None:
            return []
        return [self._action(
            "builders", "production", f"Produire {self.db.name(builder)} à {city.name}",
            f"{plural(todo, 'ressource')} à aménager pour {plural(have, 'bâtisseur')}",
            71, target_type=builder, city_id=city.city_id,
        )]

    def _improvable(self, resource: str) -> bool:
        return any(
            self._buildable(i) is not None for i in self.db.improvements_for_resource.get(resource, ())
        )

    def improvements(self) -> list[Action]:
        actions = []
        for resource, generic in self.plan.improvements:
            improvement = self._buildable(generic)
            if improvement is None:
                continue
            todo = sum(
                t.resource == resource and t.owner == "self" and t.improvement is None for t in self.state.tiles
            )
            if todo:
                count = f"{todo} × " if todo > 1 else ""
                actions.append(self._action(
                    f"improve:{resource}", "unit", f"Aménager {count}{self.db.name(improvement)}",
                    f"{plural(todo, 'gisement')} de {self.db.name(resource).lower()} non exploité{'s' if todo > 1 else ''}",
                    70, target_type=improvement,
                ))
        return actions
