-- CivOvlJson.lua
-- Sérialiseur JSON minimal pour Lua 5.1 (spec 01 §2.4).
-- Nommé avec un préfixe pour éviter une collision de nom dans le VFS de Civ VI.
--
-- Conventions :
--   CivOvlJson.null        -> null (une valeur nil disparaît d'une table Lua)
--   CivOvlJson.object(t)   -> force l'export en objet (utile pour une table vide)
--   table vide non marquée -> []

CivOvlJson = {}

local NULL = setmetatable({}, { __tostring = function() return "null" end })
local OBJECT_MT = {}

CivOvlJson.null = NULL

function CivOvlJson.object(t)
	return setmetatable(t or {}, OBJECT_MT)
end

local ESCAPES = {
	['"'] = '\\"',
	['\\'] = '\\\\',
	['\b'] = '\\b',
	['\f'] = '\\f',
	['\n'] = '\\n',
	['\r'] = '\\r',
	['\t'] = '\\t',
}

local function EncodeString(s)
	return '"' .. s:gsub('[%c"\\]', function(c)
		return ESCAPES[c] or string.format("\\u%04x", c:byte())
	end) .. '"'
end

local function EncodeNumber(n)
	-- NaN et infinis ne sont pas représentables en JSON.
	if n ~= n or n == math.huge or n == -math.huge then
		return "null"
	end
	if n == math.floor(n) and math.abs(n) < 2^53 then
		return string.format("%d", n)
	end
	return string.format("%.14g", n)
end

local function IsArray(t)
	if getmetatable(t) == OBJECT_MT then
		return false
	end
	local count = 0
	for k, _ in pairs(t) do
		if type(k) ~= "number" or k < 1 or k ~= math.floor(k) then
			return false
		end
		count = count + 1
	end
	return count == #t
end

local Encode

local function EncodeTable(t, out)
	if IsArray(t) then
		out[#out + 1] = "["
		for i = 1, #t do
			if i > 1 then out[#out + 1] = "," end
			Encode(t[i], out)
		end
		out[#out + 1] = "]"
		return
	end

	-- Clés triées : sortie déterministe, plus simple à comparer entre deux tours.
	local keys = {}
	for k, _ in pairs(t) do
		keys[#keys + 1] = tostring(k)
	end
	table.sort(keys)

	out[#out + 1] = "{"
	for i, k in ipairs(keys) do
		if i > 1 then out[#out + 1] = "," end
		out[#out + 1] = EncodeString(k)
		out[#out + 1] = ":"
		local v = t[k]
		if v == nil then v = t[tonumber(k)] end
		Encode(v, out)
	end
	out[#out + 1] = "}"
end

Encode = function(v, out)
	local kind = type(v)
	if v == nil or v == NULL then
		out[#out + 1] = "null"
	elseif kind == "boolean" then
		out[#out + 1] = v and "true" or "false"
	elseif kind == "number" then
		out[#out + 1] = EncodeNumber(v)
	elseif kind == "string" then
		out[#out + 1] = EncodeString(v)
	elseif kind == "table" then
		EncodeTable(v, out)
	else
		error("CivOvlJson: type non sérialisable : " .. kind)
	end
end

function CivOvlJson.encode(v)
	local out = {}
	Encode(v, out)
	return table.concat(out)
end
