using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class CaptureResolutionTests
{
    [Theory]
    [InlineData(1280, 720)]
    [InlineData(720, 1280)]
    [InlineData(1920, 1080)]
    [InlineData(333, 222)]
    public void BothProjectedEdgesMeetTarget(int width, int height)
    {
        var result = CaptureResolution.Calculate(width, height, .05, -.04, -.025, -.02, 128, 16384);
        double x = Math.Sqrt(Math.Pow(.05 * result.Width, 2) + Math.Pow(.04 * result.Height, 2));
        double y = Math.Sqrt(Math.Pow(.025 * result.Width, 2) + Math.Pow(.02 * result.Height, 2));
        Assert.True(x >= 128); Assert.True(y >= 128);
    }

    [Fact]
    public void WindowPixelCountDoesNotSetOutputResolution()
    {
        var small = CaptureResolution.Calculate(1280, 720, .04, -.02, -.04, -.02, 128, 16384);
        var large = CaptureResolution.Calculate(2560, 1440, .04, -.02, -.04, -.02, 128, 16384);
        Assert.Equal(small, large);
    }

    [Fact]
    public void SmallerTilesRequireLargerImages()
    {
        var smallBoard = CaptureResolution.Calculate(1280, 720, .08, -.04, -.08, -.04, 128, 16384);
        var largeBoard = CaptureResolution.Calculate(1280, 720, .04, -.02, -.04, -.02, 128, 16384);
        Assert.InRange(largeBoard.Width, smallBoard.Width * 2 - 1, smallBoard.Width * 2);
        Assert.InRange(largeBoard.Height, smallBoard.Height * 2 - 1, smallBoard.Height * 2);
    }

    [Fact]
    public void DimensionAndPixelCapsFailRatherThanClamp()
    {
        Assert.Throws<InvalidOperationException>(() => CaptureResolution.Calculate(1280, 720, .04, -.02, -.04, -.02, 128, 1024));
        Assert.Throws<InvalidOperationException>(() => CaptureResolution.Calculate(1280, 720, .001, -.001, -.001, -.001, 128, 16384));
        Assert.Throws<InvalidOperationException>(() => CaptureResolution.Calculate(1280, 720, .008, -.008, -.008, -.008, 128, 16384));
    }

    [Fact]
    public void InvalidProjectionIsRejected()
    {
        Assert.Throws<ArgumentException>(() => CaptureResolution.Calculate(1280, 720, double.NaN, .02, -.04, -.02, 128, 16384));
        Assert.Throws<ArgumentException>(() => CaptureResolution.Calculate(1280, 720, 0, 0, -.04, -.02, 128, 16384));
        Assert.Throws<ArgumentException>(() => CaptureResolution.Calculate(1280, 720, .04, -.02, .08, -.04, 128, 16384));
    }

    [Theory]
    [InlineData(null, 128)]
    [InlineData("32", 32)]
    [InlineData("256", 256)]
    [InlineData("512", 512)]
    public void ConfigurationHasDefaultAndRange(string? value, int expected) => Assert.Equal(expected, CaptureResolution.ParseTarget(value));

    [Theory]
    [InlineData("")]
    [InlineData("31")]
    [InlineData("513")]
    [InlineData("128.5")]
    [InlineData("abc")]
    public void InvalidConfigurationIsRejected(string value) => Assert.Throws<ArgumentException>(() => CaptureResolution.ParseTarget(value));
}
