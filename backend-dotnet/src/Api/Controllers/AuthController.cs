using Api.Services;
using Google.Apis.Auth;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;

namespace Api.Controllers;

[ApiController]
[Route("api/auth")]
public class AuthController : ControllerBase
{
    private readonly JwtOptions _options;
    private readonly GoogleOptions _googleOptions;
    private readonly JwtTokenService _tokenService;
    private readonly RefreshTokenStore _refreshTokens;
    private readonly LocalUserStore _localUsers;
    private readonly ILogger<AuthController> _logger;

    public AuthController(
        IOptions<JwtOptions> options,
        IOptions<GoogleOptions> googleOptions,
        JwtTokenService tokenService,
        RefreshTokenStore refreshTokens,
        LocalUserStore localUsers,
        ILogger<AuthController> logger)
    {
        _options = options.Value;
        _googleOptions = googleOptions.Value;
        _tokenService = tokenService;
        _refreshTokens = refreshTokens;
        _localUsers = localUsers;
        _logger = logger;
    }

    [HttpPost("login")]
    public IActionResult Login([FromBody] LoginRequest request)
    {
        if (request is null || string.IsNullOrWhiteSpace(request.Username) || string.IsNullOrWhiteSpace(request.Password))
        {
            _logger.LogWarning("Login fallido: request vacío o usuario/password vacío");
            return Unauthorized();
        }

        var normalizedUsername = request.Username.Trim();
        _logger.LogInformation("Intento de login para usuario: {Username}", normalizedUsername);

        // 1) Check hardcoded users first
        var user = _options.Users.FirstOrDefault(u =>
            string.Equals(u.Username, normalizedUsername, StringComparison.OrdinalIgnoreCase));

        if (user is not null && VerifyPassword(user, request.Password))
        {
            _logger.LogInformation("Login exitoso (hardcoded) para usuario: {Username}", user.Username);
            return IssueLoginResponse(user.Username, user.Role);
        }

        // 2) Check local registered users (by email)
        if (_localUsers.VerifyPassword(normalizedUsername, request.Password))
        {
            var localUser = _localUsers.FindByEmail(normalizedUsername)!;
            _logger.LogInformation("Login exitoso (local) para usuario: {Email}", localUser.Email);
            return IssueLoginResponse(localUser.Email, localUser.Role);
        }

        _logger.LogWarning("Login fallido para usuario: {Username}", normalizedUsername);
        return Unauthorized();
    }

    [HttpPost("register")]
    public IActionResult Register([FromBody] RegisterRequest request)
    {
        if (request is null
            || string.IsNullOrWhiteSpace(request.Email)
            || string.IsNullOrWhiteSpace(request.Password))
        {
            return BadRequest(new { error = "Correo y contrasena son requeridos" });
        }

        if (!_localUsers.TryRegister(request.Email, request.Password, "User", out var error))
        {
            return BadRequest(new { error });
        }

        // Auto-login after registration
        return IssueLoginResponse(request.Email.Trim().ToLowerInvariant(), "User");
    }

    private IActionResult IssueLoginResponse(string username, string role)
    {
        var token = _tokenService.CreateToken(username, role);
        var refresh = _refreshTokens.IssueToken(
            username,
            role,
            TimeSpan.FromMinutes(_options.RefreshTokenExpirationMinutes));

        return Ok(new LoginResponse(
            token,
            refresh.Token,
            username,
            role,
            _tokenService.GetAccessTokenExpiry()
        ));
    }

    [HttpPost("refresh")]
    public IActionResult Refresh([FromBody] RefreshRequest request)
    {
        if (request is null || string.IsNullOrWhiteSpace(request.RefreshToken))
        {
            _logger.LogWarning("Refresh fallido: refreshToken vacío");
            return Unauthorized();
        }

        var refreshToken = request.RefreshToken.Trim();
        _logger.LogInformation("Intento de refresh con token: {TokenPrefix}... (ocultado)", refreshToken[..Math.Min(8, refreshToken.Length)]);
        if (!_refreshTokens.TryUseToken(refreshToken, out var entry))
        {
            _logger.LogWarning("Refresh fallido: refreshToken inválido o expirado");
            return Unauthorized();
        }

        var token = _tokenService.CreateToken(entry.Username, entry.Role);
        var refresh = _refreshTokens.IssueToken(
            entry.Username,
            entry.Role,
            TimeSpan.FromMinutes(_options.RefreshTokenExpirationMinutes));

        _logger.LogInformation("Refresh exitoso para usuario: {Username}", entry.Username);
        return Ok(new LoginResponse(
            token,
            refresh.Token,
            entry.Username,
            entry.Role,
            _tokenService.GetAccessTokenExpiry()
        ));
    }

    [HttpPost("logout")]
    public IActionResult Logout([FromBody] RefreshRequest request)
    {
        if (!string.IsNullOrWhiteSpace(request?.RefreshToken))
        {
            _refreshTokens.RevokeToken(request.RefreshToken.Trim());
            _logger.LogInformation("Logout: refreshToken revocado para token: {TokenPrefix}... (ocultado)", request.RefreshToken[..Math.Min(8, request.RefreshToken.Length)]);
        }
        else
        {
            _logger.LogInformation("Logout: sin refreshToken proporcionado");
        }

        return NoContent();
    }

    private static bool VerifyPassword(JwtUser user, string password)
    {
        if (string.IsNullOrWhiteSpace(user.PasswordHash))
        {
            return false;
        }

        return BCrypt.Net.BCrypt.Verify(password, user.PasswordHash);
    }

    [HttpPost("google")]
    public async Task<IActionResult> GoogleLogin([FromBody] GoogleLoginRequest request)
    {
        if (string.IsNullOrWhiteSpace(request?.IdToken))
        {
            return BadRequest(new { error = "id_token is required" });
        }

        if (string.IsNullOrWhiteSpace(_googleOptions.ClientId))
        {
            _logger.LogError("Google:ClientId is not configured");
            return StatusCode(500, new { error = "Google login is not configured" });
        }

        GoogleJsonWebSignature.Payload payload;
        try
        {
            var settings = new GoogleJsonWebSignature.ValidationSettings
            {
                Audience = new[] { _googleOptions.ClientId }
            };
            payload = await GoogleJsonWebSignature.ValidateAsync(request.IdToken, settings);
        }
        catch (InvalidJwtException ex)
        {
            _logger.LogWarning(ex, "Invalid Google ID token received");
            return Unauthorized(new { error = "Invalid Google token" });
        }

        var email = payload.Email;
        if (string.IsNullOrWhiteSpace(email) || !payload.EmailVerified)
        {
            return Unauthorized(new { error = "Google account email is not verified" });
        }

        var role = _googleOptions.AdminEmails
            .Any(e => string.Equals(e, email, StringComparison.OrdinalIgnoreCase))
            ? "Admin"
            : "User";

        var username = payload.Name ?? email.Split('@')[0];

        _logger.LogInformation("Google login successful for {Email} as {Role}", email, role);

        var token = _tokenService.CreateToken(username, role);
        var refresh = _refreshTokens.IssueToken(
            username,
            role,
            TimeSpan.FromMinutes(_options.RefreshTokenExpirationMinutes));

        return Ok(new LoginResponse(
            token,
            refresh.Token,
            username,
            role,
            _tokenService.GetAccessTokenExpiry()
        ));
    }
}

public sealed record LoginRequest(string Username, string Password);
public sealed record RegisterRequest(string Email, string Password);
public sealed record GoogleLoginRequest(string IdToken);
public sealed record RefreshRequest(string RefreshToken);
public sealed record LoginResponse(string Token, string RefreshToken, string Username, string Role, DateTime ExpiresAt);


