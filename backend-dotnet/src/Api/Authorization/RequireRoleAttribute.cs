using Microsoft.AspNetCore.Authorization;

namespace Api.Authorization;

public sealed class RequireRoleAttribute : AuthorizeAttribute
{
    public RequireRoleAttribute(string role)
    {
        Roles = role;
    }
}
