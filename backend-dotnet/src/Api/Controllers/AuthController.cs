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

    public AuthController(IOptions<JwtOptions> options, JwtTokenService tokenService)
    {
        _options = options.Value;
        _tokenService = tokenService;
    }

    [HttpPost("login")]
    public IActionResult Login([FromBody] LoginRequest request)
    {
        var user = _options.Users.FirstOrDefault(u =>
            string.Equals(u.Username, request.Username, StringComparison.OrdinalIgnoreCase)
            && u.Password == request.Password);

        if (user is null)
        {
            return Unauthorized();
        }

        var token = _tokenService.CreateToken(user.Username, user.Role);
        return Ok(new LoginResponse(token, user.Username, user.Role));
    }
}

public sealed record LoginRequest(string Username, string Password);
public sealed record LoginResponse(string Token, string Username, string Role);
