using System.Text;
using System.Text.Json;

namespace Shared.Json;

public sealed class UpperSnakeCaseNamingPolicy : JsonNamingPolicy
{
    public override string ConvertName(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            return name;
        }

        var builder = new StringBuilder();
        for (var i = 0; i < name.Length; i++)
        {
            var c = name[i];
            if (char.IsUpper(c) && i > 0)
            {
                builder.Append('_');
            }
            builder.Append(char.ToUpperInvariant(c));
        }

        return builder.ToString();
    }
}
