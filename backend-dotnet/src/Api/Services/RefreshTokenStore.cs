using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.Extensions.Options;
using Shared.Options;

namespace Api.Services;

public sealed class RefreshTokenStore
{
    private readonly ConcurrentDictionary<string, RefreshTokenEntry> _tokens = new();
    private readonly RefreshTokenOptions _options;
    private readonly ILogger<RefreshTokenStore> _logger;
    private readonly object _lock = new();
    private readonly string _storagePath;
    private readonly IDataProtector _protector;

    public RefreshTokenStore(
        IOptions<RefreshTokenOptions> options,
        ILogger<RefreshTokenStore> logger,
        IHostEnvironment env,
        IDataProtectionProvider dataProtectionProvider)
    {
        _options = options.Value;
        _logger = logger;
        _storagePath = ResolvePath(_options.StoragePath, env.ContentRootPath);
        _protector = dataProtectionProvider.CreateProtector("RefreshTokenStore.v1");
        LoadFromDisk();
        RevokeExpired();
    }

    public RefreshTokenEntry IssueToken(string username, string role, TimeSpan lifetime)
    {
        var raw = Convert.ToBase64String(RandomNumberGenerator.GetBytes(64));
        var entry = new RefreshTokenEntry(Hash(raw), username, role, DateTime.UtcNow.Add(lifetime));
        _tokens[entry.Token] = entry;
        Persist();
        return entry with { Token = raw };
    }

    public bool TryUseToken(string token, out RefreshTokenEntry entry)
    {
        entry = default!;
        var key = Hash(token);
        if (!_tokens.TryRemove(key, out var stored))
        {
            return false;
        }

        if (stored.ExpiresAt <= DateTime.UtcNow)
        {
            Persist();
            return false;
        }

        entry = stored;
        Persist();
        return true;
    }

    public void RevokeToken(string token)
    {
        var key = Hash(token);
        _tokens.TryRemove(key, out _);
        Persist();
    }

    private void LoadFromDisk()
    {
        try
        {
            if (!File.Exists(_storagePath))
            {
                return;
            }

            var payload = File.ReadAllText(_storagePath);
            string json;
            try
            {
                json = _protector.Unprotect(payload);
            }
            catch (CryptographicException)
            {
                var trimmed = payload.TrimStart();
                if (trimmed.StartsWith("[", StringComparison.Ordinal) || trimmed.StartsWith("{", StringComparison.Ordinal))
                {
                    json = payload;
                    _logger.LogWarning("Refresh token store is not encrypted yet. It will be encrypted on next write.");
                }
                else
                {
                    _logger.LogWarning("Refresh token store payload cannot be decrypted with current keys. Skipping load.");
                    return;
                }
            }
            var entries = JsonSerializer.Deserialize<List<RefreshTokenEntry>>(json) ?? new List<RefreshTokenEntry>();
            foreach (var entry in entries)
            {
                if (entry.ExpiresAt > DateTime.UtcNow)
                {
                    _tokens[entry.Token] = entry;
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to load refresh tokens from disk.");
        }
    }

    private void Persist()
    {
        lock (_lock)
        {
            try
            {
                var directory = Path.GetDirectoryName(_storagePath);
                if (!string.IsNullOrWhiteSpace(directory))
                {
                    Directory.CreateDirectory(directory);
                }
                var entries = _tokens.Values.ToList();
                var json = JsonSerializer.Serialize(entries);
                var payload = _protector.Protect(json);
                File.WriteAllText(_storagePath, payload);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to persist refresh tokens to disk.");
            }
        }
    }

    public void RevokeExpired()
    {
        var now = DateTime.UtcNow;
        var expired = _tokens.Where(pair => pair.Value.ExpiresAt <= now).Select(pair => pair.Key).ToList();
        foreach (var key in expired)
        {
            _tokens.TryRemove(key, out _);
        }
        if (expired.Count > 0)
        {
            Persist();
        }
    }

    private static string Hash(string token)
    {
        var bytes = SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(token));
        return Convert.ToBase64String(bytes);
    }

    private static string ResolvePath(string path, string root)
    {
        if (Path.IsPathRooted(path))
        {
            return path;
        }
        return Path.Combine(root, path);
    }
}

public sealed record RefreshTokenEntry(string Token, string Username, string Role, DateTime ExpiresAt);
