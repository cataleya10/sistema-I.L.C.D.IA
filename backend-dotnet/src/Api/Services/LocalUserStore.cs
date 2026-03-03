using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.Extensions.Hosting;

namespace Api.Services;

public sealed class LocalUserStore
{
    private readonly ConcurrentDictionary<string, LocalUserEntry> _users = new(StringComparer.OrdinalIgnoreCase);
    private readonly ILogger<LocalUserStore> _logger;
    private readonly object _lock = new();
    private readonly string _storagePath;
    private readonly IDataProtector _protector;

    public LocalUserStore(
        ILogger<LocalUserStore> logger,
        IHostEnvironment env,
        IDataProtectionProvider dataProtectionProvider)
    {
        _logger = logger;
        var storageRoot = Path.Combine(env.ContentRootPath, "storage");
        Directory.CreateDirectory(storageRoot);
        _storagePath = Path.Combine(storageRoot, "local_users.json");
        _protector = dataProtectionProvider.CreateProtector("LocalUserStore.v1");
        LoadFromDisk();
    }

    public bool TryRegister(string email, string password, string role, out string error)
    {
        email = email.Trim().ToLowerInvariant();

        if (string.IsNullOrWhiteSpace(email) || !email.Contains('@'))
        {
            error = "Correo invalido";
            return false;
        }

        if (string.IsNullOrWhiteSpace(password) || password.Length < 6)
        {
            error = "La contrasena debe tener al menos 6 caracteres";
            return false;
        }

        var hash = BCrypt.Net.BCrypt.HashPassword(password);
        var entry = new LocalUserEntry(email, hash, role, DateTime.UtcNow);

        if (!_users.TryAdd(email, entry))
        {
            error = "El correo ya esta registrado";
            return false;
        }

        Persist();
        _logger.LogInformation("New local user registered: {Email} as {Role}", email, role);
        error = string.Empty;
        return true;
    }

    public LocalUserEntry? FindByEmail(string email)
    {
        email = email.Trim().ToLowerInvariant();
        return _users.TryGetValue(email, out var entry) ? entry : null;
    }

    public bool VerifyPassword(string email, string password)
    {
        var user = FindByEmail(email);
        if (user is null || string.IsNullOrWhiteSpace(user.PasswordHash))
        {
            return false;
        }

        return BCrypt.Net.BCrypt.Verify(password, user.PasswordHash);
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
            if (string.IsNullOrWhiteSpace(payload))
            {
                return;
            }

            var json = _protector.Unprotect(payload);
            var entries = JsonSerializer.Deserialize<List<LocalUserEntry>>(json);
            if (entries is null)
            {
                return;
            }

            foreach (var entry in entries)
            {
                _users[entry.Email.ToLowerInvariant()] = entry;
            }

            _logger.LogInformation("Loaded {Count} local users from disk.", entries.Count);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to load local users from disk. Starting fresh.");
        }
    }

    private void Persist()
    {
        lock (_lock)
        {
            try
            {
                var entries = _users.Values.ToList();
                var json = JsonSerializer.Serialize(entries);
                var payload = _protector.Protect(json);
                File.WriteAllText(_storagePath, payload);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to persist local users to disk.");
            }
        }
    }
}

public sealed record LocalUserEntry(string Email, string PasswordHash, string Role, DateTime CreatedAt);
