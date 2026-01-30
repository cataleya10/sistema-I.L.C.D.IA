using System.Collections.Concurrent;
using System.Security.Cryptography;

namespace Api.Services;

public sealed class RefreshTokenStore
{
    private readonly ConcurrentDictionary<string, RefreshTokenEntry> _tokens = new();

    public RefreshTokenEntry IssueToken(string username, string role, TimeSpan lifetime)
    {
        var token = Convert.ToBase64String(RandomNumberGenerator.GetBytes(64));
        var entry = new RefreshTokenEntry(token, username, role, DateTime.UtcNow.Add(lifetime));
        _tokens[token] = entry;
        return entry;
    }

    public bool TryUseToken(string token, out RefreshTokenEntry entry)
    {
        entry = default!;
        if (!_tokens.TryRemove(token, out var stored))
        {
            return false;
        }

        if (stored.ExpiresAt <= DateTime.UtcNow)
        {
            return false;
        }

        entry = stored;
        return true;
    }

    public void RevokeToken(string token)
    {
        _tokens.TryRemove(token, out _);
    }
}

public sealed record RefreshTokenEntry(string Token, string Username, string Role, DateTime ExpiresAt);
