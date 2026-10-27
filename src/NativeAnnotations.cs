using System.Text.Json;
using Polytopia.Data;
using UnityEngine;

namespace BoardCaptureLoop;

internal static class NativeAnnotations
{
    internal static TileAnnotationDocument Read(GameState state, Guid replayId, byte playerId, bool revealed, Action<string> log)
    {
        var mapping = AnnotationMapping.Default;
        int size = state.Map.Width;
        var document = new TileAnnotationDocument
        {
            ReplayId = replayId.ToString("D"), PlayerId = playerId, View = revealed ? "revealed" : "normal", Size = size,
            GridFile = $"player-{playerId}-{(revealed ? "revealed" : "normal")}.grid.json", MappingVersion = AnnotationMapping.Version
        };
        var tiles = new List<TileAnnotation>();
        PlayerState? viewer = null;
        foreach (PlayerState player in state.PlayerStates) if (player.Id == playerId) { viewer = player; break; }
        if (viewer == null) throw new InvalidDataException("Missing viewing player.");
        var transient = new SkinVisualsTransientData();
        int nature = 0;
        for (int y = 0; y < size; y++)
        for (int x = 0; x < size; x++)
        {
            try
            {
                Tile tile = MapRenderer.Current.GetTileInstance(new WorldCoordinates(x, y)) ?? throw new InvalidDataException("Missing rendered tile.");
                if (tile.IsHidden)
                {
                    if (revealed) throw new InvalidDataException("Revealed view still contains fog.");
                    tiles.Add(TileAnnotation.Masked(x, y)); continue;
                }
                TileData data = tile.Data;
                transient.SetupForTile(state, state.GameLogicData, tile);
                TribeAndSkin theme = transient.GetTileClimateSettings();
                int tribe = mapping.MapTribe(theme.tribe.ToString()), skin = mapping.MapSkin(theme.skin.ToString());
                var annotation = new TileAnnotation
                {
                    X = x, Y = y, Fog = false,
                    Terrain = VisibleTerrain(tile, mapping), Road = data.hasRoad,
                    Improvement = data.improvement == null ? 0 : mapping.MapImprovement(data.improvement.type.ToString()),
                    TerrainTribeSkin = mapping.CompactAppearance(tribe, skin),
                    TerrainAppearance = new AppearanceAnnotation { TribeId = tribe, SkinId = skin }
                };
                if (tribe == 1) nature++;
                if (data.improvement == null && data.resource != null && tile.Resource != null && tile.Resource.gameObject.activeInHierarchy &&
                    state.GameLogicData.IsResourceVisibleToPlayer(data.resource.type, viewer, state))
                    annotation.Resource = mapping.MapResource(data.resource.type.ToString());
                Unit unit = tile.Unit;
                if (unit != null && unit.GetVisible() && !unit.IsInvisibleForLocalPlayer())
                {
                    transient.SetupForUnit(state.GameLogicData, unit.UnitState, unit.Owner);
                    TribeAndSkin identity = transient.GetUnitTribeSettings();
                    VerifyUnitAppearance(unit, transient, identity);
                    int unitTribe = mapping.MapTribe(identity.tribe.ToString()), unitSkin = mapping.MapSkin(identity.skin.ToString());
                    Color color = ClientPlayerExtensions.GetPlayerColor(unit.Owner, state);
                    int[] rgb = { Mathf.RoundToInt(color.r * 255), Mathf.RoundToInt(color.g * 255), Mathf.RoundToInt(color.b * 255) };
                    int hp = UnitAnnotation.DisplayHealth(unit.UnitState.health, true);
                    var display = unit.statusDisplay;
                    if (display != null && display.IsUsed && display.unit != null && display.unit.Pointer == unit.Pointer &&
                        display.healthContainer != null && display.healthContainer.gameObject.activeInHierarchy && display.healthLabel != null &&
                        display.healthLabel.gameObject.activeInHierarchy && int.TryParse(display.healthLabel.text, out int shown) && shown != hp)
                        throw new InvalidDataException($"HP conversion disagrees with native display: {hp} vs {shown}.");
                    annotation.MainUnit = new UnitAnnotation
                    {
                        Type = mapping.MapUnit(unit.UnitState.type.ToString()), TribeSkin = mapping.CompactAppearance(unitTribe, unitSkin),
                        TribeId = unitTribe, SkinId = unitSkin, ColorRgb = rgb, ColorName = mapping.ColorName(rgb), Hp = hp
                    };
                }
                // The status display is pooled; read the live unit association, not a guessed child object.
                if (unit != null && unit.statusDisplay != null)
                {
                    UnitStatusDisplay display = unit.statusDisplay;
                    if (display.IsUsed && display.unit != null && display.unit.Pointer == unit.Pointer && display.typeContainer != null &&
                        display.typeContainer.gameObject.activeInHierarchy && display.typeIcon != null && display.typeIcon.enabled && display.typeIcon.sprite != null)
                    {
                        string sprite = display.typeIcon.sprite.name;
                        annotation.TopRightUnitIcon = new UnitIconAnnotation { Type = IconType(sprite, mapping) };
                    }
                }
                tiles.Add(annotation);
            }
            catch (Exception e) { throw new InvalidDataException($"Replay {replayId:D}, player {playerId}, {(revealed ? "revealed" : "normal")}, tile ({x},{y}): {e.Message}", e); }
        }
        document.Tiles = tiles;
        TileAnnotationValidator.Validate(document);
        log($"Replay {replayId:D}, player {playerId}, {document.View}: {nature} visible Nature terrain tiles.");
        return document;
    }

    private static int VisibleTerrain(Tile tile, AnnotationMapping mapping)
    {
        string sprite = tile.terrainRenderer?.SpriteRenderer?.GetSpriteName() ?? throw new InvalidDataException("Missing terrain sprite.");
        string name = sprite.ToLowerInvariant();
        if (tile.Data.terrain == Polytopia.Data.TerrainData.Type.Mangrove) return mapping.MapTerrain("Mangrove");
        if (tile.forestRenderer != null && tile.forestRenderer.gameObject.activeInHierarchy && tile.forestRenderer.Sprite != null)
            return mapping.MapTerrain("Forest");
        if (tile.mountainRenderer != null && tile.mountainRenderer.gameObject.activeInHierarchy && tile.mountainRenderer.Sprite != null)
            return mapping.MapTerrain("Mountain");
        if (name.Contains("wetland")) return mapping.MapTerrain("Wetland");
        return mapping.MapTerrain(tile.Data.terrain.ToString());
    }

    private static void VerifyUnitAppearance(Unit unit, SkinVisualsTransientData transient, TribeAndSkin identity)
    {
        if (unit.skinVisuals == null || unit.skinVisuals.visualParts == null) throw new InvalidDataException("Missing unit visual parts.");
        foreach (var part in unit.skinVisuals.visualParts)
        {
            if (part.visualPart == null || !part.visualPart.activeInHierarchy) continue;
            string partName = (part.DefaultSpriteName ?? part.visualPart.name).ToLowerInvariant();
            if (!partName.Contains("head") && !partName.Contains("body")) continue;
            TribeAndSkin resolved;
            switch (part.skinLogic)
            {
                case SkinVisualsReference.SkinningLogic.UseTribe: resolved = transient.GetUnitTribeSettings(); break;
                case SkinVisualsReference.SkinningLogic.UseClimate: resolved = transient.GetUnitClimateSettings(); break;
                case SkinVisualsReference.SkinningLogic.UseBirthClimate: resolved = transient.GetUnitBirthClimateSettings(); break;
                case SkinVisualsReference.SkinningLogic.DontChangeSkin: continue;
                default: throw new InvalidDataException("Unsupported unit skinning rule.");
            }
            if (resolved.tribe != identity.tribe || resolved.skin != identity.skin)
                throw new InvalidDataException($"Unit head/body appearance mismatch: {identity.tribe}/{identity.skin} vs {resolved.tribe}/{resolved.skin} ({part.DefaultSpriteName}).");
        }
    }

    private static int IconType(string sprite, AnnotationMapping mapping)
    {
        string name = sprite.Replace("(Clone)", "").Trim();
        if (name.EndsWith("_icon", StringComparison.OrdinalIgnoreCase)) name = name.Substring(0, name.Length - 5);
        if (name.StartsWith("unit_", StringComparison.OrdinalIgnoreCase)) name = name.Substring(5);
        name = name.ToLowerInvariant() switch
        {
            "explorer" => "Scout", "rebel" => "Bunny", "rammer" => "Rammership", "pirate_ship" => "Pirate", _ => name
        };
        return mapping.MapUnit(name);
    }
}
