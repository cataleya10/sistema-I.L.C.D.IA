using Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;

namespace Api.Controllers;

[ApiController]
[Route("api/auth")]
public class AuthController : ControllerBase
{
    private readonly JwtOptions _options;
    private readonly JwtTokenService _tokenService;
    private readonly RefreshTokenStore _refreshTokens;

    public AuthController(IOptions<JwtOptions> options, JwtTokenService tokenService, RefreshTokenStore refreshTokens)
    {
        _options = options.Value;
        _tokenService = tokenService;
        _refreshTokens = refreshTokens;
    }

    [HttpPost("login")]
    public IActionResult Login([FromBody] LoginRequest request)
    {
        var user = _options.Users.FirstOrDefault(u =>
            string.Equals(u.Username, request.Username, StringComparison.OrdinalIgnoreCase));

        if (user is null || !VerifyPassword(user, request.Password))
        {
            return Unauthorized();
        }

        var token = _tokenService.CreateToken(user.Username, user.Role);
        var refresh = _refreshTokens.IssueToken(
            user.Username,
            user.Role,
            TimeSpan.FromMinutes(_options.RefreshTokenExpirationMinutes));

        return Ok(new LoginResponse(
            token,
            refresh.Token,
            user.Username,
            user.Role,
            _tokenService.GetAccessTokenExpiry()
        ));
    }

    [HttpPost("refresh")]
    public IActionResult Refresh([FromBody] RefreshRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.RefreshToken))
        {
            return Unauthorized();
        }

        if (!_refreshTokens.TryUseToken(request.RefreshToken, out var entry))
        {
            return Unauthorized();
        }

        var token = _tokenService.CreateToken(entry.Username, entry.Role);
        var refresh = _refreshTokens.IssueToken(
            entry.Username,
            entry.Role,
            TimeSpan.FromMinutes(_options.RefreshTokenExpirationMinutes));

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
        if (!string.IsNullOrWhiteSpace(request.RefreshToken))
        {
            _refreshTokens.RevokeToken(request.RefreshToken);
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
}

public sealed record LoginRequest(string Username, string Password);
public sealed record RefreshRequest(string RefreshToken);
public sealed record LoginResponse(string Token, string RefreshToken, string Username, string Role, DateTime ExpiresAt);


