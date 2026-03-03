using Api.Controllers;
using Api.Services;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Shared.Options;
using Xunit;

namespace Infrastructure.Tests;

public class AuthControllerTests : IDisposable
{
    private readonly string _tempDir;
    private readonly JwtOptions _jwtOptions;
    private readonly GoogleOptions _googleOptions;
    private readonly JwtTokenService _tokenService;
    private readonly RefreshTokenStore _refreshTokenStore;
    private readonly AuthController _controller;

    public AuthControllerTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"ilcdia-test-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);

        _jwtOptions = new JwtOptions
        {
            Issuer = "test-issuer",
            Audience = "test-audience",
            SigningKey = "ThisIsASuperSecretKeyForTestingPurposesOnly1234567890!",
            ExpirationMinutes = 30,
            RefreshTokenExpirationMinutes = 60,
            Users = new List<JwtUser>
            {
                new() { Username = "admin", PasswordHash = BCrypt.Net.BCrypt.HashPassword("admin123"), Role = "Admin" },
                new() { Username = "user1", PasswordHash = BCrypt.Net.BCrypt.HashPassword("user123"), Role = "User" }
            }
        };

        _googleOptions = new GoogleOptions
        {
            ClientId = "test-google-client-id",
            AdminEmails = new List<string> { "admin@example.com" }
        };

        _tokenService = new JwtTokenService(Options.Create(_jwtOptions));

        var refreshOptions = new RefreshTokenOptions
        {
            StoragePath = Path.Combine(_tempDir, "refresh_tokens.json"),
            CleanupIntervalMinutes = 60
        };

        var env = new TestHostEnvironment
        {
            ContentRootPath = _tempDir,
            EnvironmentName = "Testing"
        };

        _refreshTokenStore = new RefreshTokenStore(
            Options.Create(refreshOptions),
            NullLogger<RefreshTokenStore>.Instance,
            env,
            new EphemeralDataProtectionProvider());

        _controller = new AuthController(
            Options.Create(_jwtOptions),
            Options.Create(_googleOptions),
            _tokenService,
            _refreshTokenStore,
            NullLogger<AuthController>.Instance);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, true); } catch { /* cleanup best-effort */ }
    }

    // ─── Login ────────────────────────────────────────────────

    [Fact]
    public void Login_ValidCredentials_ReturnsOkWithTokens()
    {
        var result = _controller.Login(new LoginRequest("admin", "admin123"));

        var ok = Assert.IsType<OkObjectResult>(result);
        var response = Assert.IsType<LoginResponse>(ok.Value);
        Assert.False(string.IsNullOrWhiteSpace(response.Token));
        Assert.False(string.IsNullOrWhiteSpace(response.RefreshToken));
        Assert.Equal("admin", response.Username);
        Assert.Equal("Admin", response.Role);
    }

    [Fact]
    public void Login_InvalidPassword_ReturnsUnauthorized()
    {
        var result = _controller.Login(new LoginRequest("admin", "wrong-password"));

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Login_UnknownUser_ReturnsUnauthorized()
    {
        var result = _controller.Login(new LoginRequest("nobody", "test"));

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Login_EmptyUsername_ReturnsUnauthorized()
    {
        var result = _controller.Login(new LoginRequest("", "test"));

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Login_NullRequest_ReturnsUnauthorized()
    {
        var result = _controller.Login(null!);

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Login_IsCaseInsensitive()
    {
        var result = _controller.Login(new LoginRequest("ADMIN", "admin123"));

        var ok = Assert.IsType<OkObjectResult>(result);
        var response = Assert.IsType<LoginResponse>(ok.Value);
        Assert.Equal("admin", response.Username);
    }

    [Fact]
    public void Login_TrimmedUsername_Matches()
    {
        var result = _controller.Login(new LoginRequest("  admin  ", "admin123"));

        var ok = Assert.IsType<OkObjectResult>(result);
        var response = Assert.IsType<LoginResponse>(ok.Value);
        Assert.Equal("admin", response.Username);
    }

    // ─── Refresh ──────────────────────────────────────────────

    [Fact]
    public void Refresh_ValidToken_ReturnsNewTokens()
    {
        var loginResult = _controller.Login(new LoginRequest("admin", "admin123"));
        var loginResponse = Assert.IsType<LoginResponse>(Assert.IsType<OkObjectResult>(loginResult).Value);

        var result = _controller.Refresh(new RefreshRequest(loginResponse.RefreshToken));

        var ok = Assert.IsType<OkObjectResult>(result);
        var response = Assert.IsType<LoginResponse>(ok.Value);
        Assert.False(string.IsNullOrWhiteSpace(response.Token));
        Assert.Equal("admin", response.Username);
        Assert.Equal("Admin", response.Role);
    }

    [Fact]
    public void Refresh_InvalidToken_ReturnsUnauthorized()
    {
        var result = _controller.Refresh(new RefreshRequest("invalid-token"));

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Refresh_NullRequest_ReturnsUnauthorized()
    {
        var result = _controller.Refresh(null!);

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Refresh_EmptyToken_ReturnsUnauthorized()
    {
        var result = _controller.Refresh(new RefreshRequest(""));

        Assert.IsType<UnauthorizedResult>(result);
    }

    [Fact]
    public void Refresh_TokenIsOneTimeUse()
    {
        var loginResult = _controller.Login(new LoginRequest("admin", "admin123"));
        var loginResponse = Assert.IsType<LoginResponse>(Assert.IsType<OkObjectResult>(loginResult).Value);
        var refreshToken = loginResponse.RefreshToken;

        // First refresh succeeds
        var first = _controller.Refresh(new RefreshRequest(refreshToken));
        Assert.IsType<OkObjectResult>(first);

        // Second refresh with the SAME token fails (one-time-use)
        var second = _controller.Refresh(new RefreshRequest(refreshToken));
        Assert.IsType<UnauthorizedResult>(second);
    }

    // ─── Logout ───────────────────────────────────────────────

    [Fact]
    public void Logout_ReturnsNoContent()
    {
        var loginResult = _controller.Login(new LoginRequest("admin", "admin123"));
        var loginResponse = Assert.IsType<LoginResponse>(Assert.IsType<OkObjectResult>(loginResult).Value);

        var result = _controller.Logout(new RefreshRequest(loginResponse.RefreshToken));

        Assert.IsType<NoContentResult>(result);
    }

    [Fact]
    public void Logout_WithNullToken_ReturnsNoContent()
    {
        var result = _controller.Logout(new RefreshRequest(null!));

        Assert.IsType<NoContentResult>(result);
    }

    [Fact]
    public void Refresh_AfterLogout_ReturnsUnauthorized()
    {
        var loginResult = _controller.Login(new LoginRequest("admin", "admin123"));
        var loginResponse = Assert.IsType<LoginResponse>(Assert.IsType<OkObjectResult>(loginResult).Value);
        var refreshToken = loginResponse.RefreshToken;

        _controller.Logout(new RefreshRequest(refreshToken));

        var result = _controller.Refresh(new RefreshRequest(refreshToken));
        Assert.IsType<UnauthorizedResult>(result);
    }

    // ─── Google Login ─────────────────────────────────────────

    [Fact]
    public async Task GoogleLogin_EmptyIdToken_ReturnsBadRequest()
    {
        var result = await _controller.GoogleLogin(new GoogleLoginRequest(""));

        Assert.IsType<BadRequestObjectResult>(result);
    }

    [Fact]
    public async Task GoogleLogin_NullRequest_ReturnsBadRequest()
    {
        var result = await _controller.GoogleLogin(null!);

        Assert.IsType<BadRequestObjectResult>(result);
    }

    [Fact]
    public async Task GoogleLogin_UnconfiguredClientId_Returns500()
    {
        var emptyGoogleOptions = new GoogleOptions { ClientId = "" };
        var controller = new AuthController(
            Options.Create(_jwtOptions),
            Options.Create(emptyGoogleOptions),
            _tokenService,
            _refreshTokenStore,
            NullLogger<AuthController>.Instance);

        var result = await controller.GoogleLogin(new GoogleLoginRequest("some-token"));

        var statusResult = Assert.IsType<ObjectResult>(result);
        Assert.Equal(500, statusResult.StatusCode);
    }

    [Fact]
    public async Task GoogleLogin_InvalidToken_ReturnsUnauthorized()
    {
        var result = await _controller.GoogleLogin(new GoogleLoginRequest("invalid-garbage-token"));

        Assert.IsType<UnauthorizedObjectResult>(result);
    }

    // ─── Helpers ──────────────────────────────────────────────

    private sealed class TestHostEnvironment : IHostEnvironment
    {
        public string ApplicationName { get; set; } = "Test";
        public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
        public string ContentRootPath { get; set; } = Path.GetTempPath();
        public string EnvironmentName { get; set; } = "Testing";
    }
}
