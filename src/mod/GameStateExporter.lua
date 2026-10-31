-- GameStateExporter.lua
-- Exporte l'état du joueur local vers Lua.log (spec 01).
-- Appels d'API repris de l'UI officielle du jeu (CitySupport, TopPanel, TechTree, GovernmentScreen…).

include("CivOvlJson")

local Json = CivOvlJson

local SCHEMA_VERSION = 1
local MARKER = "[CIVOVL]"
local LOG_PREFIX = "[CIVOVL-INFO]"
local CHUNK_SIZE = 900  -- octets par fragment (spec 01 §4.2)
local TILE_RADIUS = 3   -- rayon d'exploitation d'une ville (spec 01 §2.3)
-- Déclencheurs qui exportent la carte détaillée des villes (`cities[].plots`, volumineuse).
local PLOTS_TRIGGERS = { game_loaded = true, turn_begin = true }

local m_msgId = 0
local m_reportedErrors = {}

-- os.clock n'a qu'une résolution d'une seconde dans le jeu (constaté le 2026-10-29) :
-- on lui préfère Automation.GetTime quand il est accessible depuis ce contexte.
local Clock, CLOCK_NAME
if Automation ~= nil and Automation.GetTime ~= nil and pcall(Automation.GetTime) then
	Clock, CLOCK_NAME = Automation.GetTime, "Automation.GetTime"
elseif os ~= nil and os.clock ~= nil then
	Clock, CLOCK_NAME = os.clock, "os.clock"
else
	Clock, CLOCK_NAME = function() return 0 end, "aucun"
end

-- ===========================================================================
-- Utilitaires
-- ===========================================================================

-- Exécute une section d'extraction ; en cas d'erreur, la section est omise
-- et l'erreur signalée une seule fois par session.
local function ReportOnce(section, message)
	if not m_reportedErrors[section] then
		m_reportedErrors[section] = true
		print(LOG_PREFIX .. " Section '" .. section .. "' ignorée : " .. tostring(message))
	end
end

local function Safe(section, fn, ...)
	local ok, result = pcall(fn, ...)
	if ok then
		return result
	end
	ReportOnce(section, result)
	return nil
end

-- Chaîne `Type` d'une ligne GameInfo à partir d'un index, d'un hash ou d'un type ; nil si absente.
local function TypeName(infoTable, key, field)
	if key == nil or key == -1 then
		return nil
	end
	local row = infoTable[key]
	if row == nil then
		return nil
	end
	return row[field]
end

local function ReadConfigValue(getConfig, key)
	local ok, value = pcall(function() return getConfig().GetValue(key) end)
	if ok and value ~= nil then
		return tostring(value)
	end
	return nil
end

-- ===========================================================================
-- Extraction (spec 01 §5)
-- ===========================================================================

-- Identifiant stable d'une partie : identique d'un rechargement à l'autre.
local function BuildGameId(leader)
	local mapSeed = ReadConfigValue(function() return MapConfiguration end, "RANDOM_SEED")
	local gameSeed = ReadConfigValue(function() return GameConfiguration end, "GAME_SYNC_RANDOM_SEED")
	if mapSeed == nil and gameSeed == nil then
		return nil
	end
	return leader .. "_" .. (mapSeed or "x") .. "_" .. (gameSeed or "x")
end

local function ExtractGame(playerId)
	local game = { turn = Game.GetCurrentGameTurn() }
	game.era = Safe("game.era", function()
		return TypeName(GameInfo.Eras, Game.GetEras():GetCurrentEra(), "EraType")
	end)
	game.game_speed = Safe("game.game_speed", function()
		return TypeName(GameInfo.GameSpeeds, GameConfiguration.GetGameSpeedType(), "GameSpeedType")
	end)
	game.difficulty = Safe("game.difficulty", function()
		return TypeName(GameInfo.Difficulties, PlayerConfigurations[playerId]:GetHandicapTypeID(), "DifficultyType")
	end)
	game.map_size = Safe("game.map_size", function()
		return TypeName(GameInfo.Maps, Map.GetMapSize(), "MapSizeType")
	end)
	game.ruleset = Safe("game.ruleset", function() return GameConfiguration.GetRuleSet() end)
	return game
end

local function ExtractPlayer(playerId, player)
	local config = PlayerConfigurations[playerId]
	local info = {
		player_id = playerId,
		civilization = config:GetCivilizationTypeName(),
		leader = config:GetLeaderTypeName(),
	}
	local culture = player:GetCulture()
	info.religion = Safe("player.religion", function()
		return TypeName(GameInfo.Religions, player:GetReligion():GetReligionTypeCreated(), "ReligionType")
	end) or Json.null
	info.government = Safe("player.government", function()
		return TypeName(GameInfo.Governments, culture:GetCurrentGovernment(), "GovernmentType")
	end) or Json.null
	info.policies = Safe("player.policies", function()
		local policies = {}
		for slot = 0, culture:GetNumPolicySlots() - 1 do
			local policy = TypeName(GameInfo.Policies, culture:GetSlotPolicy(slot), "PolicyType")
			if policy ~= nil then
				policies[#policies + 1] = policy
			end
		end
		return policies
	end)
	return info
end

local function ExtractYields(player)
	local treasury = player:GetTreasury()
	local religion = player:GetReligion()
	return {
		gold = treasury:GetGoldBalance(),
		-- Même calcul que le TopPanel du jeu : revenu brut moins l'entretien.
		gold_per_turn = treasury:GetGoldYield() - treasury:GetTotalMaintenance(),
		science_per_turn = player:GetTechs():GetScienceYield(),
		culture_per_turn = player:GetCulture():GetCultureYield(),
		faith = religion:GetFaithBalance(),
		faith_per_turn = religion:GetFaithYield(),
	}
end

local function ExtractTechs(player)
	local techs = player:GetTechs()
	local result = { current_research = Json.null, researched = {}, boosted = {} }
	for row in GameInfo.Technologies() do
		if techs:HasTech(row.Index) then
			result.researched[#result.researched + 1] = row.TechnologyType
		elseif techs:HasBoostBeenTriggered(row.Index) then
			result.boosted[#result.boosted + 1] = row.TechnologyType
		end
	end

	local current = techs:GetResearchingTech()
	local row = (current ~= nil and current >= 0) and GameInfo.Technologies[current] or nil
	if row ~= nil then
		result.current_research = row.TechnologyType
		result.research_progress = techs:GetResearchProgress(current)
		result.research_cost = techs:GetResearchCost(current)
	end
	return result
end

local function ExtractCivics(player)
	local culture = player:GetCulture()
	local result = { current_civic = Json.null, unlocked = {}, boosted = {} }
	for row in GameInfo.Civics() do
		if culture:HasCivic(row.Index) then
			result.unlocked[#result.unlocked + 1] = row.CivicType
		elseif culture:HasBoostBeenTriggered(row.Index) then
			result.boosted[#result.boosted + 1] = row.CivicType
		end
	end

	local current = culture:GetProgressingCivic()
	local row = (current ~= nil and current >= 0) and GameInfo.Civics[current] or nil
	if row ~= nil then
		result.current_civic = row.CivicType
		result.civic_progress = culture:GetCulturalProgress(current)
		result.civic_cost = culture:GetCultureCost(current)
	end
	return result
end

local function ExtractStrategicResources(player)
	local resources = player:GetResources()
	local result = Json.object({})
	for row in GameInfo.Resources() do
		if row.ResourceClassType == "RESOURCECLASS_STRATEGIC" then
			local amount = resources:GetResourceAmount(row.ResourceType)
			if amount ~= nil and amount > 0 then
				result[row.ResourceType] = amount
			end
		end
	end
	return result
end

-- Type et avancement de la production en cours (cf. CitySupport.GetProductionInfoOfCity).
local function ProductionInfo(queue)
	local hash = queue:GetCurrentProductionTypeHash()
	if hash == nil or hash == 0 then
		return nil, nil
	end
	local building = GameInfo.Buildings[hash]
	if building ~= nil then
		return building.BuildingType, queue:GetBuildingProgress(building.Index)
	end
	local district = GameInfo.Districts[hash]
	if district ~= nil then
		return district.DistrictType, queue:GetDistrictProgress(district.Index)
	end
	local unit = GameInfo.Units[hash]
	if unit ~= nil then
		return unit.UnitType, queue:GetUnitProgress(unit.Index)
	end
	local project = GameInfo.Projects[hash]
	if project ~= nil then
		return project.ProjectType, queue:GetProjectProgress(project.Index)
	end
	return nil, nil
end

-- Ville au bord de l'eau (mer ou lac) : condition pour produire des unités navales.
local function IsCoastal(cx, cy)
	for dx = -1, 1 do
		for dy = -1, 1 do
			local plot = Map.GetPlot(cx + dx, cy + dy)
			if plot ~= nil and plot:IsWater() and Map.GetPlotDistance(cx, cy, plot:GetX(), plot:GetY()) == 1 then
				return true
			end
		end
	end
	return false
end

-- Quartiers dont on évalue les emplacements (et leurs remplacements uniques) : quartiers de
-- spécialité, puis quartiers de soutien qui donnent des bonus aux voisins (Aqueduc -> Zone
-- industrielle, Complexe de divertissement -> Théâtre, Quartier résidentiel / Mbanza…), et ceux
-- de fin de partie. CanHaveDistrict ignore les prérequis (technologie, dogme) : les quartiers pas
-- encore débloqués sont évalués aussi, pour planifier la ville. Les types absents de la
-- configuration (DLC non installé) sont ignorés.
local SITE_DISTRICTS = {
	"DISTRICT_CAMPUS", "DISTRICT_COMMERCIAL_HUB", "DISTRICT_THEATER", "DISTRICT_HOLY_SITE",
	"DISTRICT_INDUSTRIAL_ZONE", "DISTRICT_ENCAMPMENT", "DISTRICT_HARBOR",
	"DISTRICT_AQUEDUCT", "DISTRICT_DAM", "DISTRICT_ENTERTAINMENT_COMPLEX", "DISTRICT_NEIGHBORHOOD",
	"DISTRICT_GOVERNMENT", "DISTRICT_DIPLOMATIC_QUARTER", "DISTRICT_PRESERVE",
	"DISTRICT_WATER_ENTERTAINMENT_COMPLEX", "DISTRICT_AERODROME", "DISTRICT_SPACEPORT",
}
local m_siteDistricts = nil

-- Traits de la civilisation et du leader du joueur local.
local function LocalPlayerTraits()
	local config = PlayerConfigurations[Game.GetLocalPlayer()]
	local civilization, leader = config:GetCivilizationTypeName(), config:GetLeaderTypeName()
	local traits = {}
	for row in GameInfo.CivilizationTraits() do
		if row.CivilizationType == civilization then
			traits[row.TraitType] = true
		end
	end
	for row in GameInfo.LeaderTraits() do
		if row.LeaderType == leader then
			traits[row.TraitType] = true
		end
	end
	return traits
end

-- Quartiers que le joueur peut construire : CanHaveDistrict accepte aussi les quartiers uniques
-- d'autres civilisations (constaté le 2026-10-29), on les écarte donc ici. Si la civilisation
-- a une version unique, elle remplace le quartier générique.
local function SiteDistricts()
	if m_siteDistricts ~= nil then
		return m_siteDistricts
	end
	local traits = LocalPlayerTraits()
	local wanted = {}
	for _, districtType in ipairs(SITE_DISTRICTS) do
		wanted[districtType] = true
	end
	for row in GameInfo.DistrictReplaces() do
		local unique = GameInfo.Districts[row.CivUniqueDistrictType]
		if wanted[row.ReplacesDistrictType] and unique ~= nil and traits[unique.TraitType] then
			wanted[row.ReplacesDistrictType] = nil
			wanted[row.CivUniqueDistrictType] = true
		end
	end
	m_siteDistricts = {}
	for row in GameInfo.Districts() do
		if wanted[row.DistrictType] and (row.TraitType == nil or traits[row.TraitType]) then
			m_siteDistricts[#m_siteDistricts + 1] = row
		end
	end
	return m_siteDistricts
end

-- Quartiers (absents de la ville) que la tuile peut accueillir, avec leur adjacence :
-- validité et adjacence calculées par le jeu lui-même (cf. AdjacencyBonusSupport.lua).
local function PlotSites(plot, playerId, cityId, placedDistricts)
	local sites = Json.object({})
	for _, district in ipairs(SiteDistricts()) do
		if not placedDistricts[district.DistrictType] and plot:CanHaveDistrict(district.Index, playerId, cityId) then
			local adjacency = 0
			for yield in GameInfo.Yields() do
				adjacency = adjacency + plot:GetAdjacencyYield(playerId, cityId, district.Index, yield.Index)
			end
			sites[district.DistrictType] = adjacency
		end
	end
	return sites
end

-- Tuiles révélées des 3 premiers anneaux autour de la ville (zone où un quartier peut être placé,
-- tuiles à acheter comprises).
local function RingPlots(city, visibility)
	local cx, cy = city:GetX(), city:GetY()
	local plots, seen = {}, {}
	for dx = -TILE_RADIUS, TILE_RADIUS do
		for dy = -TILE_RADIUS, TILE_RADIUS do
			local plot = Map.GetPlot(cx + dx, cy + dy)
			if plot ~= nil and not seen[plot:GetIndex()] then
				seen[plot:GetIndex()] = true
				local x, y = plot:GetX(), plot:GetY()
				if Map.GetPlotDistance(cx, cy, x, y) <= TILE_RADIUS and visibility:IsRevealed(x, y) then
					plots[#plots + 1] = plot
				end
			end
		end
	end
	return plots
end

-- Tuile appartenant à une autre civilisation : aucun quartier possible.
local function IsForeign(plot, playerId)
	local owner = plot:GetOwner()
	return owner ~= nil and owner >= 0 and owner ~= playerId
end

-- Nom de l'autre ville du joueur qui possède la tuile, ou nil (tuile libre ou de cette ville).
local function OtherCityName(plot, playerId, cityId)
	if plot:GetOwner() ~= playerId then
		return nil
	end
	local owningCity = Cities.GetPlotPurchaseCity(plot)
	if owningCity == nil or owningCity:GetID() == cityId then
		return nil
	end
	return Locale.Lookup(owningCity:GetName())
end

-- Meilleur emplacement de chaque quartier absent de la ville, parmi ses tuiles.
local function BestSites(sitesByPlot)
	local best = Json.object({})
	for _, item in ipairs(sitesByPlot) do
		for districtType, adjacency in pairs(item.sites) do
			local current = best[districtType]
			if current == nil or adjacency > current.adjacency then
				best[districtType] = { adjacency = adjacency, hex_x = item.plot:GetX(), hex_y = item.plot:GetY() }
			end
		end
	end
	return best
end

-- Carte détaillée de la ville (spec 01 §5, `cities[].plots`) : les tuiles révélées des 3 premiers
-- anneaux, avec les quartiers possibles et leur adjacence (sauf tuiles d'une autre civilisation).
-- Les voisins sont donnés par le jeu : pas de convention de grille à deviner.
local function DescribePlot(plot, playerId, visibility, playerResources)
	local x, y = plot:GetX(), plot:GetY()
	local owner = plot:GetOwner()
	local entry = {
		index = plot:GetIndex(),
		hex_x = x,
		hex_y = y,
		terrain = TypeName(GameInfo.Terrains, plot:GetTerrainType(), "TerrainType"),
		feature = TypeName(GameInfo.Features, plot:GetFeatureType(), "FeatureType"),
		district = TypeName(GameInfo.Districts, plot:GetDistrictType(), "DistrictType"),
		neighbors = {},
	}
	for direction = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1 do
		local adjacent = Map.GetAdjacentPlot(x, y, direction)
		entry.neighbors[#entry.neighbors + 1] = adjacent ~= nil and adjacent:GetIndex() or -1
	end
	local resource = GameInfo.Resources[plot:GetResourceType()]
	if resource ~= nil and playerResources:IsResourceVisible(resource.Hash) then
		entry.resource = resource.ResourceType
	end
	if visibility:IsVisible(x, y) or owner == playerId then
		entry.improvement = TypeName(GameInfo.Improvements, plot:GetImprovementType(), "ImprovementType")
	end
	if plot:IsRiver() then
		entry.river = true
	end
	return entry
end

local function ExtractCityPlots(city, playerId, placedDistricts)
	local visibility = PlayersVisibility[playerId]
	local playerResources = Players[playerId]:GetResources()
	local cityId = city:GetID()
	local purchased = {}
	for _, plotId in pairs(Map.GetCityPlots():GetPurchasedPlots(city) or {}) do
		purchased[plotId] = true
	end

	local plots, sitesByPlot = {}, {}
	for _, plot in ipairs(RingPlots(city, visibility)) do
		local entry = DescribePlot(plot, playerId, visibility, playerResources)
		entry.owned = purchased[plot:GetIndex()] == true
		local otherCity = Safe("OtherCityName", OtherCityName, plot, playerId, cityId)
		if IsForeign(plot, playerId) then
			entry.foreign = true
		elseif otherCity ~= nil then
			-- Tuile d'une autre ville du joueur : ses quartiers sont dessinés, mais pas de site ici.
			entry.other_city = otherCity
			entry.sites = Json.object({})
		else
			entry.sites = PlotSites(plot, playerId, cityId, placedDistricts)
			sitesByPlot[#sitesByPlot + 1] = { plot = plot, sites = entry.sites }
		end
		plots[#plots + 1] = entry
	end
	return plots, BestSites(sitesByPlot)
end

-- Merveilles que la ville peut lancer maintenant (`CanProduce` : prérequis acquis, pas encore
-- construites ailleurs), avec les tuiles où le jeu autorise à les placer (comme l'écran de
-- placement, StrategicView_MapPlacement.lua) : tuiles déjà achetées par la ville seulement.
local function WonderSites(city)
	local sites = Json.object({})
	local queue = city:GetBuildQueue()
	for row in GameInfo.Buildings() do
		if row.IsWonder and queue:CanProduce(row.Hash, true) then
			local params = {}
			params[CityOperationTypes.PARAM_BUILDING_TYPE] = row.Hash
			local results = CityManager.GetOperationTargets(city, CityOperationTypes.BUILD, params)
			local plots = {}
			if results ~= nil and results[CityOperationResults.PLOTS] ~= nil then
				for _, plotId in ipairs(results[CityOperationResults.PLOTS]) do
					plots[#plots + 1] = plotId
				end
			end
			sites[row.BuildingType] = plots
		end
	end
	return sites
end

local function ExtractCity(city, includePlots)
	local growth = city:GetGrowth()
	local entry = {
		city_id = city:GetID(),
		name = Locale.Lookup(city:GetName()),
		is_capital = city:IsCapital(),
		hex_x = city:GetX(),
		hex_y = city:GetY(),
		population = city:GetPopulation(),
		housing = growth:GetHousing(),
		amenities_surplus = growth:GetAmenities() - growth:GetAmenitiesNeeded(),
		coastal = IsCoastal(city:GetX(), city:GetY()),
		current_production = Json.null,
		districts = {},
		buildings = {},
	}

	local queue = city:GetBuildQueue()
	local productionType, progress = ProductionInfo(queue)
	if productionType ~= nil then
		entry.current_production = productionType
		entry.production_progress = progress
		entry.production_turns_left = queue:GetTurnsLeft()
	end

	local placedDistricts = {}
	for _, district in city:GetDistricts():Members() do
		local districtType = TypeName(GameInfo.Districts, district:GetType(), "DistrictType")
		if districtType ~= nil then
			placedDistricts[districtType] = true  -- en construction compris
			if district:IsComplete() then
				entry.districts[#entry.districts + 1] = districtType
			end
		end
	end
	local cityDistricts = city:GetDistricts()
	entry.district_slots = Safe("district_slots", function()
		return {
			used = cityDistricts:GetNumZonedDistrictsRequiringPopulation(),
			allowed = cityDistricts:GetNumAllowedDistrictsRequiringPopulation(),
		}
	end)

	-- Carte détaillée et meilleurs emplacements : seulement en début de tour (coût et volume) ;
	-- le moteur garde la dernière version reçue pour les autres déclencheurs (spec 02 §7).
	if includePlots then
		local ok, plots, sites = pcall(ExtractCityPlots, city, city:GetOwner(), placedDistricts)
		if ok then
			entry.plots, entry.district_sites = plots, sites
		else
			ReportOnce("plots", plots)
		end
		entry.wonder_sites = Safe("wonder_sites", WonderSites, city)
	end

	local buildings = city:GetBuildings()
	for row in GameInfo.Buildings() do
		if buildings:HasBuilding(row.Index) then
			entry.buildings[#entry.buildings + 1] = row.BuildingType
		end
	end
	return entry
end

local function ExtractCities(player, includePlots)
	local cities = {}
	for _, city in player:GetCities():Members() do
		local entry = Safe("cities", ExtractCity, city, includePlots)
		if entry ~= nil then
			cities[#cities + 1] = entry
		end
	end
	return cities
end

local function ExtractUnits(player)
	local units = {}
	for _, unit in player:GetUnits():Members() do
		local row = GameInfo.Units[unit:GetType()]
		if row ~= nil then
			units[#units + 1] = {
				unit_id = unit:GetID(),
				type = row.UnitType,
				formation_class = row.FormationClass,
				hex_x = unit:GetX(),
				hex_y = unit:GetY(),
				hp = unit:GetMaxDamage() - unit:GetDamage(),
				moves_left = unit:GetMovesRemaining(),
			}
		end
	end
	return units
end

-- Tuiles révélées dans un rayon de TILE_RADIUS autour des villes du joueur (spec 01 §2.2).
local function ExtractTiles(playerId, player)
	local visibility = PlayersVisibility[playerId]
	local playerResources = player:GetResources()
	local seen = {}
	local tiles = {}

	for _, city in player:GetCities():Members() do
		local cx, cy = city:GetX(), city:GetY()
		for dx = -TILE_RADIUS, TILE_RADIUS do
			for dy = -TILE_RADIUS, TILE_RADIUS do
				local plot = Map.GetPlot(cx + dx, cy + dy)
				if plot ~= nil and not seen[plot:GetIndex()] then
					seen[plot:GetIndex()] = true
					local x, y = plot:GetX(), plot:GetY()
					if Map.GetPlotDistance(cx, cy, x, y) <= TILE_RADIUS and visibility:IsRevealed(x, y) then
						local isVisible = visibility:IsVisible(x, y)
						local owner = plot:GetOwner()
						local tile = {
							hex_x = x,
							hex_y = y,
							terrain = TypeName(GameInfo.Terrains, plot:GetTerrainType(), "TerrainType"),
							feature = TypeName(GameInfo.Features, plot:GetFeatureType(), "FeatureType"),
							visible = isVisible,
						}
						if plot:IsRiver() then
							tile.river = true
						end
						if owner == playerId then
							tile.owner = "self"
						elseif owner ~= nil and owner >= 0 then
							tile.owner = "other"
						end

						local resource = GameInfo.Resources[plot:GetResourceType()]
						if resource ~= nil and playerResources:IsResourceVisible(resource.Hash) then
							tile.resource = resource.ResourceType
						end
						-- Hors vue, les aménagements d'autrui ont pu changer : on ne les exporte pas.
						if isVisible or owner == playerId then
							tile.improvement = TypeName(GameInfo.Improvements, plot:GetImprovementType(), "ImprovementType")
						end
						tiles[#tiles + 1] = tile
					end
				end
			end
		end
	end
	return tiles
end

-- Carte de colonisation (spec 01 §5, `settle_map`) : tuiles révélées dans un rayon de SETTLE_RADIUS
-- autour des villes du joueur et de SETTLER_RADIUS autour de ses colons. Balayage borné (pas de
-- carte entière), seulement en début de tour. Le moteur en déduit eau douce, côte et distances.
local SETTLE_RADIUS = 8
local SETTLER_RADIUS = 5

local function ExtractSettleMap(playerId, player)
	local visibility = PlayersVisibility[playerId]
	local playerResources = player:GetResources()
	local width, height = Map.GetGridSize()
	local centers = {}
	for _, city in player:GetCities():Members() do
		centers[#centers + 1] = { city:GetX(), city:GetY(), SETTLE_RADIUS }
	end
	for _, unit in player:GetUnits():Members() do
		local info = GameInfo.Units[unit:GetType()]
		if info ~= nil and info.FoundCity then
			centers[#centers + 1] = { unit:GetX(), unit:GetY(), SETTLER_RADIUS }
		end
	end

	local seen, tiles = {}, {}
	for _, center in ipairs(centers) do
		local cx, cy, radius = center[1], center[2], center[3]
		for dx = -radius, radius do
			for dy = -radius, radius do
				-- Coordonnées ramenées dans la carte (cartes qui bouclent d'est en ouest).
				local plot = Map.GetPlot((cx + dx) % width, cy + dy)
				if plot ~= nil and not seen[plot:GetIndex()] then
					local x, y = plot:GetX(), plot:GetY()
					if Map.GetPlotDistance(cx, cy, x, y) <= radius and visibility:IsRevealed(x, y) then
						seen[plot:GetIndex()] = true
						local tile = {
							hex_x = x,
							hex_y = y,
							terrain = TypeName(GameInfo.Terrains, plot:GetTerrainType(), "TerrainType"),
							feature = TypeName(GameInfo.Features, plot:GetFeatureType(), "FeatureType"),
						}
						local feature = GameInfo.Features[plot:GetFeatureType()]
						if feature ~= nil and feature.NaturalWonder then
							tile.natural_wonder = true
						end
						if plot:IsRiver() then
							tile.river = true
						end
						if plot:IsLake() then
							tile.lake = true
						end
						local owner = plot:GetOwner()
						if owner == playerId then
							tile.owner = "self"
						elseif owner ~= nil and owner >= 0 then
							tile.owner = "other"
						end
						if plot:IsCity() then
							tile.city = (owner == playerId) and "self" or "other"
						end
						local resource = GameInfo.Resources[plot:GetResourceType()]
						if resource ~= nil and playerResources:IsResourceVisible(resource.Hash) then
							tile.resource = resource.ResourceType
						end
						tiles[#tiles + 1] = tile
					end
				end
			end
		end
	end
	return { map_width = width, map_height = height, tiles = tiles }
end

local function ExtractKnownPlayers(playerId, player)
	local diplomacy = player:GetDiplomacy()
	local known = {}
	for _, otherId in ipairs(PlayerManager.GetAliveMajorIDs()) do
		if otherId ~= playerId and diplomacy:HasMet(otherId) then
			local config = PlayerConfigurations[otherId]
			known[#known + 1] = {
				player_id = otherId,
				civilization = config:GetCivilizationTypeName(),
				leader = config:GetLeaderTypeName(),
				-- Nom affiché en jeu : couvre les civilisations de mods absentes de la base de traduction.
				name = Locale.Lookup(config:GetCivilizationShortDescription()),
				at_war = diplomacy:IsAtWarWith(otherId),
			}
		end
	end
	return known
end

local function BuildGameState(trigger)
	local playerId = Game.GetLocalPlayer()
	if playerId == nil or playerId < 0 then
		return nil  -- observateur / autoplay : rien à exporter
	end
	local player = Players[playerId]
	local playerInfo = ExtractPlayer(playerId, player)
	local settleMap = nil
	if PLOTS_TRIGGERS[trigger] then
		settleMap = Safe("settle_map", ExtractSettleMap, playerId, player)
	end

	return {
		schema_version = SCHEMA_VERSION,
		meta = { trigger = trigger, game_id = BuildGameId(playerInfo.leader) },
		game = ExtractGame(playerId),
		player = playerInfo,
		yields = ExtractYields(player),
		techs = ExtractTechs(player),
		civics = Safe("civics", ExtractCivics, player),
		strategic_resources = Safe("strategic_resources", ExtractStrategicResources, player),
		cities = Safe("cities", ExtractCities, player, PLOTS_TRIGGERS[trigger] == true),
		units = Safe("units", ExtractUnits, player),
		tiles = Safe("tiles", ExtractTiles, playerId, player),
		known_players = Safe("known_players", ExtractKnownPlayers, playerId, player),
		settle_map = settleMap,
	}
end

-- ===========================================================================
-- Émission fragmentée (spec 01 §4.2)
-- ===========================================================================

local function Emit(json)
	m_msgId = m_msgId + 1
	local total = math.max(1, math.ceil(#json / CHUNK_SIZE))
	for part = 1, total do
		local first = (part - 1) * CHUNK_SIZE + 1
		local payload = json:sub(first, first + CHUNK_SIZE - 1)
		print(string.format("%s %d %d/%d %s", MARKER, m_msgId, part, total, payload))
	end
end

local function Export(trigger)
	local startTime = Clock()
	local ok, stateOrError = pcall(BuildGameState, trigger)
	if not ok then
		print(LOG_PREFIX .. " Échec de l'extraction (" .. trigger .. ") : " .. tostring(stateOrError))
		return
	end
	if stateOrError == nil then
		return
	end

	local encoded, json = pcall(Json.encode, stateOrError)
	if not encoded then
		print(LOG_PREFIX .. " Échec de la sérialisation : " .. tostring(json))
		return
	end
	-- Mesure extraction + sérialisation (spec 01 §2.3) ; ajoutée au JSON déjà sérialisé
	-- pour ne pas resérialiser.
	local elapsedMs = math.floor((Clock() - startTime) * 1000 + 0.5)
	json = json:gsub('"meta":{', '"meta":{"extraction_ms":' .. elapsedMs .. ',', 1)
	Emit(json)
end

-- ===========================================================================
-- Événements (spec 01 §3)
-- ===========================================================================

local function OnLoadScreenClose()
	Export("game_loaded")
end

local function OnLocalPlayerTurnBegin()
	Export("turn_begin")
end

local function OnLocalPlayerTurnEnd()
	Export("turn_end")
end

-- Changements en cours de tour (recherche, production…) : on marque l'état comme modifié,
-- puis on exporte une seule fois à la fin de la série d'événements du moteur
-- (même motif que ResearchChooser.lua, spec 01 §3).
local m_stateDirty = false

local function OnLocalStateChanged(playerId)
	if playerId == Game.GetLocalPlayer() then
		m_stateDirty = true
	end
end

local function OnGameCoreEventPublishComplete()
	if m_stateDirty then
		m_stateDirty = false
		Export("state_changed")
	end
end

local function Initialize()
	Events.LoadScreenClose.Add(OnLoadScreenClose)
	Events.LocalPlayerTurnBegin.Add(OnLocalPlayerTurnBegin)
	Events.LocalPlayerTurnEnd.Add(OnLocalPlayerTurnEnd)
	Events.ResearchChanged.Add(OnLocalStateChanged)
	Events.CivicChanged.Add(OnLocalStateChanged)
	Events.CityProductionChanged.Add(OnLocalStateChanged)
	Events.GovernmentChanged.Add(OnLocalStateChanged)
	Events.CityAddedToMap.Add(OnLocalStateChanged)
	Events.GameCoreEventPublishComplete.Add(OnGameCoreEventPublishComplete)
	print(LOG_PREFIX .. " GameStateExporter chargé (schema_version " .. SCHEMA_VERSION .. ", chrono " .. CLOCK_NAME .. ")")
end

Initialize()
