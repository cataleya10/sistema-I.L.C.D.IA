namespace Shared.Options;

public sealed class JwtOptions
{
    public const string SectionName = "Jwt";

    public string Issuer { get; set; } = "ilcdia";
    public string Audience { get; set; } = "ilcdia-web";
    public string SigningKey { get; set; } = "CHANGE_ME_SUPER_SECRET_KEY";
    public int ExpirationMinutes { get; set; } = 60;
    public List<JwtUser> Users { get; set; } = new();
}

public sealed class JwtUser
{
    public string Username { get; set; } = string.Empty;
    public string Password { get; set; } = string.Empty;
    public string Role { get; set; } = "User";
}
