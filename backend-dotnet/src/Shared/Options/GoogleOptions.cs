namespace Shared.Options;

public sealed class GoogleOptions
{
    public const string SectionName = "Google";

    /// <summary>Google OAuth2 Client ID from Google Cloud Console.</summary>
    public string ClientId { get; set; } = string.Empty;

    /// <summary>
    /// Emails that receive the Admin role on first Google sign-in.
    /// All other emails receive the User role.
    /// </summary>
    public List<string> AdminEmails { get; set; } = new();
}
