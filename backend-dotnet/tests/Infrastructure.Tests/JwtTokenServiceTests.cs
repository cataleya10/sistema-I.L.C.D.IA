using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Api.Services;
using Microsoft.Extensions.Options;
using Shared.Options;
using Xunit;

namespace Infrastructure.Tests;

public class JwtTokenServiceTests
{
    private readonly JwtOptions _options = new()
    {
        Issuer = "test-issuer",
        Audience = "test-audience",
        SigningKey = "ThisIsASuperSecretKeyForTestingPurposesOnly1234567890!",
        ExpirationMinutes = 30
    };

    private JwtTokenService CreateService() => new(Options.Create(_options));

    [Fact]
    public void CreateToken_ReturnsNonEmptyString()
    {
        var svc = CreateService();

        var token = svc.CreateToken("admin", "Admin");

        Assert.False(string.IsNullOrWhiteSpace(token));
    }

    [Fact]
    public void CreateToken_HasCorrectSubjectClaim()
    {
        var svc = CreateService();

        var token = svc.CreateToken("admin", "Admin");

        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(token);
        Assert.Equal("admin", jwt.Subject);
    }

    [Fact]
    public void CreateToken_HasCorrectRoleClaim()
    {
        var svc = CreateService();

        var token = svc.CreateToken("admin", "Admin");

        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(token);
        var role = jwt.Claims.FirstOrDefault(c => c.Type == ClaimTypes.Role)?.Value;
        Assert.Equal("Admin", role);
    }

    [Fact]
    public void CreateToken_HasCorrectIssuerAndAudience()
    {
        var svc = CreateService();

        var token = svc.CreateToken("reviewer", "User");

        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(token);
        Assert.Equal("test-issuer", jwt.Issuer);
        Assert.Contains("test-audience", jwt.Audiences);
    }

    [Fact]
    public void CreateToken_ExpiresWithinExpectedWindow()
    {
        var svc = CreateService();
        var before = DateTime.UtcNow.AddMinutes(29);

        var token = svc.CreateToken("admin", "Admin");

        var after = DateTime.UtcNow.AddMinutes(31);
        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(token);
        Assert.InRange(jwt.ValidTo, before, after);
    }

    [Fact]
    public void CreateToken_DifferentUsersProduceDifferentTokens()
    {
        var svc = CreateService();

        var tokenA = svc.CreateToken("admin", "Admin");
        var tokenB = svc.CreateToken("analyst", "User");

        Assert.NotEqual(tokenA, tokenB);
    }

    [Fact]
    public void GetAccessTokenExpiry_ReturnsTimeInFuture()
    {
        var svc = CreateService();

        var expiry = svc.GetAccessTokenExpiry();

        Assert.True(expiry > DateTime.UtcNow);
        Assert.True(expiry < DateTime.UtcNow.AddMinutes(31));
    }
}
