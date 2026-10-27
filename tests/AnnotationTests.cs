using System.Text.Json;
using System.Text.Json.Nodes;
using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class AnnotationTests
{
    private static AnnotationMapping Mapping => AnnotationMapping.Default;
    private static TileAnnotationDocument Example(int size = 1) => new()
    {
        ReplayId = "12345678-1234-1234-1234-123456789abc", PlayerId = 1, View = "normal", Size = size,
        GridFile = "player-1-normal.grid.json",
        Tiles = Enumerable.Range(0, size * size).Select(i => new TileAnnotation
        {
            X = i % size, Y = i / size, Terrain = 3, TerrainTribeSkin = 1,
            TerrainAppearance = new AppearanceAnnotation { TribeId = 2, SkinId = 0 }
        }).ToList()
    };
    private static UnitAnnotation Warrior(int[]? color = null) => new()
    {
        Type = 2, TribeId = 7, SkinId = 5, TribeSkin = 22, Hp = 10,
        ColorRgb = color ?? new[] { 0, 0, 255 }, ColorName = Mapping.ColorName(color ?? new[] { 0, 0, 255 })
    };

    [Theory]
    [InlineData("terrain", 9)]
    [InlineData("resource", 10)]
    [InlineData("improvement", 56)]
    [InlineData("unit", 63)]
    public void PinnedEnumMapsAreComplete(string category, int count)
    {
        for (int id = 0; id < count; id++) Assert.True(Mapping.IsDefined(category, id));
        Assert.False(Mapping.IsDefined(category, count));
        Assert.False(Mapping.IsDefined(category, -1));
    }

    [Fact]
    public void NativeNamesMapWithoutAssumingNativeNumericValues()
    {
        Assert.Equal(7, Mapping.MapTerrain("Wetland"));
        Assert.Equal(9, Mapping.MapResource("Aquacrop"));
        Assert.Equal(4, Mapping.MapImprovement("CustomsHouse"));
        Assert.Equal(47, Mapping.MapImprovement("LightHouse"));
        Assert.Equal(39, Mapping.MapUnit("Cloak_Boat"));
        Assert.Equal(43, Mapping.MapUnit("Transportship"));
        Assert.Equal(19, Mapping.MapUnit("fire_dragon"));
        Assert.Equal(2, Mapping.MapUnit("WARRIOR"));
        Assert.Equal(5, Mapping.MapSkin("Scholar"));
        Assert.Equal(7, Mapping.MapTribe("Imperius"));
        Assert.Throws<InvalidDataException>(() => Mapping.MapTerrain("123"));
        Assert.Throws<InvalidDataException>(() => Mapping.MapUnit("NewFutureUnit"));
        Assert.Throws<InvalidDataException>(() => Mapping.MapImprovement("pending action"));
    }

    [Fact]
    public void EveryPlayableTribeHasExactlyItsPinnedSparsePremiumSkin()
    {
        int[] skins = { 12, 17, 3, 15, 1, 5, 11, 7, 8, 14, 9, 2, 13, 10, 18, 19 };
        for (int tribe = 2; tribe <= 17; tribe++)
        {
            Assert.True(Mapping.IsPlayableTribe(tribe));
            Assert.Equal(tribe - 1, Mapping.CompactAppearance(tribe, 0));
            Assert.Equal(tribe - 1, Mapping.CompactAppearance(tribe, -1));
            Assert.Equal(skins[tribe - 2], Mapping.PremiumSkin(tribe));
            Assert.Equal(tribe + 15, Mapping.CompactAppearance(tribe, skins[tribe - 2]));
            Assert.Throws<InvalidDataException>(() => Mapping.CompactAppearance(tribe, skins[(tribe - 1) % 16]));
        }
        Assert.Equal(0, Mapping.CompactAppearance(1, 0));
        Assert.Equal(0, Mapping.CompactAppearance(1, 17));
        Assert.Equal(0, Mapping.CompactAppearance(0, 0));
        Assert.Throws<InvalidDataException>(() => Mapping.CompactAppearance(7, 4));
        Assert.Throws<InvalidDataException>(() => Mapping.CompactAppearance(99, 0));
    }

    [Fact]
    public void LegacyStyleConversionIsExplicitAndNeverAppliedToTypedTribes()
    {
        Assert.Equal(13, Mapping.NormalizeLegacyTribe(1));
        Assert.Equal(7, Mapping.NormalizeLegacyTribe(2));
        Assert.Equal(17, Mapping.NormalizeLegacyTribe(16));
        Assert.Equal(2, Mapping.MapTribe("Aimo"));
        Assert.Throws<InvalidDataException>(() => Mapping.NormalizeLegacyTribe(17));
    }

    [Fact]
    public void ColorsUseExactRgbIncludingNatureNoneSwampAndCustomPlayerColors()
    {
        Assert.Equal("black", Mapping.ColorName(new[] { 0, 0, 0 }));
        Assert.Equal("light_gray", Mapping.ColorName(new[] { 210, 210, 210 }));
        Assert.Equal("blue", Mapping.ColorName(new[] { 0, 0, 255 }));
        Assert.Equal("olive_green", Mapping.ColorName(new[] { 103, 140, 48 }));
        Assert.Equal("other", Mapping.ColorName(new[] { 0, 0, 254 }));
        Assert.Equal(new[] { 243, 131, 129 }, Mapping.DefaultColor(3, 0));
        Assert.Equal(new[] { 103, 140, 48 }, Mapping.DefaultColor(3, 17));
        Assert.Throws<InvalidDataException>(() => Mapping.ColorName(new[] { -1, 0, 0 }));
        Assert.Throws<InvalidDataException>(() => Mapping.ColorName(new[] { 0, 0, 256 }));
        Assert.Throws<InvalidDataException>(() => Mapping.ColorName(new[] { 0, 0 }));
    }

    [Fact]
    public void DocumentRoundTripsWithAlwaysPresentSnakeCaseObjects()
    {
        var document = Example(2);
        string json = JsonSerializer.Serialize(document);
        Assert.Contains("\"main_unit\":", json);
        Assert.Contains("\"top_right_unit_icon\":", json);
        Assert.Contains("\"terrain_appearance\":", json);
        Assert.DoesNotContain("TerrainAppearance", json);
        var parsed = TileAnnotationValidator.ParseAndValidate(json);
        Assert.Equal(4, parsed.Tiles.Count);
        Assert.Equal(0, parsed.Tiles[0].MainUnit.Type);
        Assert.Equal("none", parsed.Tiles[0].MainUnit.ColorName);
    }

    [Fact]
    public void ValidFogMasksAndIndependentIconAreAccepted()
    {
        var document = Example();
        document.Tiles[0] = TileAnnotation.Masked(0, 0);
        TileAnnotationValidator.Validate(document);
        document.Tiles[0] = Example().Tiles[0];
        document.Tiles[0].TopRightUnitIcon.Type = 3;
        TileAnnotationValidator.Validate(document);
        document.Tiles[0].MainUnit = Warrior();
        TileAnnotationValidator.Validate(document);
        document.Tiles[0].TopRightUnitIcon.Type = 0;
        TileAnnotationValidator.Validate(document);
    }

    [Fact]
    public void VisibleNaturePreservesSourceIdsAndLogsCount()
    {
        var document = Example();
        var tile = document.Tiles[0];
        tile.TerrainAppearance.TribeId = 1; tile.TerrainTribeSkin = 0;
        var messages = new List<string>();
        TileAnnotationValidator.Validate(document, messages.Add);
        Assert.Contains("Nature terrain tiles=1", Assert.Single(messages));
        Assert.Equal(3, tile.Terrain);
        Assert.Equal(1, tile.TerrainAppearance.TribeId);
    }

    [Theory]
    [InlineData("terrain")]
    [InlineData("resource")]
    [InlineData("improvement")]
    [InlineData("road")]
    [InlineData("appearance")]
    [InlineData("compact")]
    [InlineData("unit")]
    [InlineData("icon")]
    public void FogOverridesEveryAttribute(string attribute)
    {
        var document = Example(); var tile = TileAnnotation.Masked(0, 0); document.Tiles[0] = tile;
        switch (attribute)
        {
            case "terrain": tile.Terrain = 3; break;
            case "resource": tile.Resource = 1; break;
            case "improvement": tile.Improvement = 1; break;
            case "road": tile.Road = true; break;
            case "appearance": tile.TerrainAppearance.TribeId = 1; break;
            case "compact": tile.TerrainTribeSkin = 1; break;
            case "unit": tile.MainUnit = Warrior(); break;
            case "icon": tile.TopRightUnitIcon.Type = 2; break;
        }
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
    }

    [Fact]
    public void RevealedCannotContainFog()
    {
        var document = Example(); document.View = "revealed"; document.GridFile = "player-1-revealed.grid.json";
        document.Tiles[0] = TileAnnotation.Masked(0, 0);
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
    }

    [Fact]
    public void ImprovementOverridesResourceIncludingOperationLikeImprovements()
    {
        var document = Example(); var tile = document.Tiles[0]; tile.Improvement = 10; tile.Resource = 6;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        tile.Resource = 0; TileAnnotationValidator.Validate(document);
        tile.Improvement = 55; TileAnnotationValidator.Validate(document);
    }

    [Fact]
    public void CompactLabelsMustMatchEffectiveSourceAppearance()
    {
        var document = Example(); var tile = document.Tiles[0]; tile.TerrainAppearance.SkinId = 12;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        tile.TerrainTribeSkin = 17; tile.MainUnit = Warrior(); TileAnnotationValidator.Validate(document);
        tile.MainUnit.SkinId = 0;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
    }

    [Fact]
    public void AbsentAndInvisibleUnitMustHaveAllZeroAttributes()
    {
        var document = Example(); document.Tiles[0].MainUnit.Hp = 1;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        document.Tiles[0].MainUnit.Hp = 0; document.Tiles[0].MainUnit.ColorName = "black";
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
    }

    [Fact]
    public void BlackVisibleUnitsAndCustomExactRgbAreNotMistakenForAbsent()
    {
        var document = Example(); var tile = document.Tiles[0]; tile.MainUnit = Warrior(new[] { 0, 0, 0 });
        TileAnnotationValidator.Validate(document);
        tile.MainUnit = Warrior(new[] { 12, 34, 56 }); TileAnnotationValidator.Validate(document);
        Assert.Equal(new[] { 12, 34, 56 }, tile.MainUnit.ColorRgb);
        tile.MainUnit.ColorName = "blue";
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        tile.MainUnit.ColorName = "other"; tile.MainUnit.Hp = -1;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
    }

    [Theory]
    [InlineData(1, true, 1)]
    [InlineData(10, true, 1)]
    [InlineData(11, true, 2)]
    [InlineData(100, true, 10)]
    [InlineData(10, false, 10)]
    [InlineData(0, true, 0)]
    [InlineData(int.MaxValue, true, 214748365)]
    public void HealthConvertsOnlyExplicitStoredTenths(int raw, bool tenths, int expected) => Assert.Equal(expected, UnitAnnotation.DisplayHealth(raw, tenths));

    [Fact]
    public void NegativeRawHealthIsRejected() => Assert.Throws<InvalidDataException>(() => UnitAnnotation.DisplayHealth(-1, true));

    [Fact]
    public void TileCountsOrderingCoordinatesAndEnumsAreChecked()
    {
        var document = Example(2); document.Tiles.Reverse();
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        document = Example(2); document.Tiles[1].X = 0;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        document = Example(2); document.Tiles.RemoveAt(0);
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        document = Example(); document.Tiles[0].Terrain = 9;
        string message = Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document)).Message;
        Assert.Contains(document.ReplayId, message); Assert.Contains("view=normal", message); Assert.Contains("tile[0] (0,0)", message);
        document.Tiles[0].Terrain = 3; document.Tiles[0].TopRightUnitIcon.Type = 63;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
    }

    [Theory]
    [InlineData("schema_version")]
    [InlineData("replay_id")]
    [InlineData("player_id")]
    [InlineData("view")]
    [InlineData("size")]
    [InlineData("grid_file")]
    [InlineData("mapping_version")]
    [InlineData("tiles")]
    public void FileValidationRequiresEveryMetadataProperty(string field)
    {
        var json = JsonSerializer.SerializeToNode(Example())!.AsObject(); json.Remove(field);
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.ParseAndValidate(json.ToJsonString()));
    }

    [Fact]
    public void FileValidationRequiresExplicitZeroAndFalseFieldsAndNestedObjects()
    {
        foreach (string field in new[] { "x", "y", "fog", "road", "resource", "main_unit", "top_right_unit_icon", "terrain_appearance" })
        {
            var json = JsonSerializer.SerializeToNode(Example())!;
            json["tiles"]![0]!.AsObject().Remove(field);
            Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.ParseAndValidate(json.ToJsonString()));
        }
        foreach (string field in new[] { "type", "tribe_skin", "tribe_id", "skin_id", "color_rgb", "color_name", "hp" })
        {
            var json = JsonSerializer.SerializeToNode(Example())!;
            json["tiles"]![0]!["main_unit"]!.AsObject().Remove(field);
            Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.ParseAndValidate(json.ToJsonString()));
        }
    }

    [Fact]
    public void InvalidMetadataNullsDuplicateFieldsAndJsonTypesAreRejected()
    {
        var document = Example(); document.MappingVersion = "future";
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        document = Example(); document.GridFile = "../elsewhere.grid.json";
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.Validate(document));
        var json = JsonSerializer.SerializeToNode(Example())!; json["tiles"]![0]!["main_unit"] = null;
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.ParseAndValidate(json.ToJsonString()));
        string serialized = JsonSerializer.Serialize(Example()).Replace("\"road\":false", "\"road\":false,\"road\":true", StringComparison.Ordinal);
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.ParseAndValidate(serialized));
        json = JsonSerializer.SerializeToNode(Example())!; json["tiles"]![0]!["fog"] = "false";
        Assert.Throws<InvalidDataException>(() => TileAnnotationValidator.ParseAndValidate(json.ToJsonString()));
    }
}
