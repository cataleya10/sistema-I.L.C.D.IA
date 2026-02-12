namespace Shared.Options;

public sealed class JwtOptions
{
    public const string SectionName = "Jwt";

    public string Issuer { get; set; } = "ilcdia";
    public string Audience { get; set; } = "ilcdia-web";
    public string SigningKey { get; set; } = string.Empty;
    public int ExpirationMinutes { get; set; } = 60;
    public int RefreshTokenExpirationMinutes { get; set; } = 60 * 24 * 7;
    public List<JwtUser> Users { get; set; } = new();
}

public sealed class JwtUser
{
    public string Username { get; set; } = string.Empty;
    public string? PasswordHash { get; set; }
    public string Role { get; set; } = "User";
}
