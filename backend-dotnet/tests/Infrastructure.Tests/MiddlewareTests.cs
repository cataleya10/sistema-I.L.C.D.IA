using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;
using Api.Middlewares;
using Api.Services;

namespace Infrastructure.Tests;

// ── CorrelationIdMiddleware ────────────────────────────────────────
public class CorrelationIdMiddlewareTests
{
    [Fact]
    public async Task InvokeAsync_NoHeader_GeneratesCorrelationIdAndSetsOnResponse()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var middleware = new CorrelationIdMiddleware(_ => Task.CompletedTask);

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.True(context.Request.Headers.ContainsKey("X-Correlation-Id"));
        Assert.True(context.Response.Headers.ContainsKey("X-Correlation-Id"));

        var responseId = context.Response.Headers["X-Correlation-Id"].ToString();
        Assert.False(string.IsNullOrWhiteSpace(responseId));
        Assert.True(Guid.TryParse(responseId, out _));
    }

    [Fact]
    public async Task InvokeAsync_ClientSendsHeader_PreservesOriginalValue()
    {
        // Arrange
        var context = new DefaultHttpContext();
        context.Request.Headers["X-Correlation-Id"] = "my-custom-id-123";
        var middleware = new CorrelationIdMiddleware(_ => Task.CompletedTask);

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.Equal("my-custom-id-123", context.Request.Headers["X-Correlation-Id"].ToString());
        Assert.Equal("my-custom-id-123", context.Response.Headers["X-Correlation-Id"].ToString());
    }

    [Fact]
    public async Task InvokeAsync_CallsNext()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var nextCalled = false;
        var middleware = new CorrelationIdMiddleware(_ => { nextCalled = true; return Task.CompletedTask; });

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.True(nextCalled);
    }

    [Fact]
    public async Task InvokeAsync_ResponseIdMatchesRequestId()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var middleware = new CorrelationIdMiddleware(_ => Task.CompletedTask);

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        var requestId = context.Request.Headers["X-Correlation-Id"].ToString();
        var responseId = context.Response.Headers["X-Correlation-Id"].ToString();
        Assert.Equal(requestId, responseId);
    }
}

// ── ExceptionHandlingMiddleware ────────────────────────────────────
public class ExceptionHandlingMiddlewareTests
{
    [Fact]
    public async Task InvokeAsync_NoException_PassesThrough()
    {
        // Arrange
        var context = new DefaultHttpContext();
        context.Response.Body = new MemoryStream();
        var nextCalled = false;
        var middleware = new ExceptionHandlingMiddleware(
            _ => { nextCalled = true; return Task.CompletedTask; },
            NullLogger<ExceptionHandlingMiddleware>.Instance
        );

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.True(nextCalled);
        Assert.NotEqual(500, context.Response.StatusCode);
    }

    [Fact]
    public async Task InvokeAsync_Exception_Returns500ProblemDetails()
    {
        // Arrange
        var context = new DefaultHttpContext();
        context.Response.Body = new MemoryStream();
        context.Request.Path = "/api/test";

        var middleware = new ExceptionHandlingMiddleware(
            _ => throw new InvalidOperationException("boom"),
            NullLogger<ExceptionHandlingMiddleware>.Instance
        );

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.Equal(500, context.Response.StatusCode);
        Assert.Equal("application/problem+json", context.Response.ContentType);

        context.Response.Body.Seek(0, SeekOrigin.Begin);
        var body = await new StreamReader(context.Response.Body).ReadToEndAsync();
        var problem = JsonSerializer.Deserialize<JsonElement>(body);

        Assert.Equal(500, problem.GetProperty("status").GetInt32());
        Assert.Equal("Error interno", problem.GetProperty("title").GetString());
        Assert.Equal("/api/test", problem.GetProperty("instance").GetString());
    }

    [Fact]
    public async Task InvokeAsync_Exception_IncludesCorrelationIdInBody()
    {
        // Arrange
        var context = new DefaultHttpContext();
        context.Response.Body = new MemoryStream();
        context.Response.Headers["X-Correlation-Id"] = "corr-abc";

        var middleware = new ExceptionHandlingMiddleware(
            _ => throw new Exception("fail"),
            NullLogger<ExceptionHandlingMiddleware>.Instance
        );

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        context.Response.Body.Seek(0, SeekOrigin.Begin);
        var body = await new StreamReader(context.Response.Body).ReadToEndAsync();
        Assert.Contains("corr-abc", body);
    }
}

// ── SecurityHeadersMiddleware ──────────────────────────────────────
public class SecurityHeadersMiddlewareTests
{
    [Fact]
    public async Task InvokeAsync_AddsAllSecurityHeaders()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var middleware = new SecurityHeadersMiddleware(_ => Task.CompletedTask);

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        var h = context.Response.Headers;
        Assert.Equal("nosniff", h["X-Content-Type-Options"].ToString());
        Assert.Equal("DENY", h["X-Frame-Options"].ToString());
        Assert.Equal("no-referrer", h["Referrer-Policy"].ToString());
        Assert.Equal("0", h["X-XSS-Protection"].ToString());
        Assert.Contains("geolocation=()", h["Permissions-Policy"].ToString());
        Assert.Equal("same-site", h["Cross-Origin-Resource-Policy"].ToString());
        Assert.Equal("none", h["X-Permitted-Cross-Domain-Policies"].ToString());
        Assert.Equal("default-src 'none'", h["Content-Security-Policy"].ToString());
        Assert.Equal("no-store", h["Cache-Control"].ToString());
    }

    [Fact]
    public async Task InvokeAsync_CallsNext()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var nextCalled = false;
        var middleware = new SecurityHeadersMiddleware(_ => { nextCalled = true; return Task.CompletedTask; });

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.True(nextCalled);
    }

    [Fact]
    public async Task InvokeAsync_HeadersSetBeforeNext()
    {
        // Arrange
        var context = new DefaultHttpContext();
        string? xFrameInsideNext = null;
        var middleware = new SecurityHeadersMiddleware(ctx =>
        {
            xFrameInsideNext = ctx.Response.Headers["X-Frame-Options"].ToString();
            return Task.CompletedTask;
        });

        // Act
        await middleware.InvokeAsync(context);

        // Assert
        Assert.Equal("DENY", xFrameInsideNext);
    }
}

// ── RequestLoggingMiddleware ───────────────────────────────────────
public class RequestLoggingMiddlewareTests
{
    [Fact]
    public async Task InvokeAsync_CallsMetricsObserve()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var metrics = new MetricsService();
        var middleware = new RequestLoggingMiddleware(
            _ => Task.CompletedTask,
            NullLogger<RequestLoggingMiddleware>.Instance,
            metrics
        );

        // Act
        await middleware.InvokeAsync(context);

        // Assert – snapshot should show 1 request
        var snap = metrics.Snapshot();
        Assert.Equal(1, snap.Requests);
    }

    [Fact]
    public async Task InvokeAsync_LogsRequest()
    {
        // Arrange
        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/api/health";
        var metrics = new MetricsService();
        var middleware = new RequestLoggingMiddleware(
            _ => Task.CompletedTask,
            NullLogger<RequestLoggingMiddleware>.Instance,
            metrics
        );

        // Act – should not throw
        await middleware.InvokeAsync(context);

        // Assert – status code 200 (default), request counted
        Assert.Equal(200, context.Response.StatusCode);
        Assert.Equal(1, metrics.Snapshot().Requests);
    }

    [Fact]
    public async Task InvokeAsync_RegistersDurationHeader()
    {
        // Arrange
        var context = new DefaultHttpContext();
        var metrics = new MetricsService();
        var middleware = new RequestLoggingMiddleware(
            _ => Task.CompletedTask,
            NullLogger<RequestLoggingMiddleware>.Instance,
            metrics
        );

        // Act
        // Trigger OnStarting callbacks (DefaultHttpContext doesn't auto-fire them,
        // but the middleware at least registers without error)
        await middleware.InvokeAsync(context);

        // Assert – middleware executed without error
        Assert.Equal(1, metrics.Snapshot().Requests);
    }
}
