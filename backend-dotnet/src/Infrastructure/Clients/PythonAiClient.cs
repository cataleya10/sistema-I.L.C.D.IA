using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using Application.DTOs;
using Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Shared.Json;

namespace Infrastructure.Clients;

public class PythonAiClient : IPythonAiClient
{
    private readonly HttpClient _httpClient;
    private readonly JsonSerializerOptions _jsonOptions;

    public PythonAiClient(HttpClient httpClient, IConfiguration configuration)
    {
        _httpClient = httpClient;
        var baseUrl = configuration["PythonAi:BaseUrl"] ?? "http://localhost:8000";
        _httpClient.BaseAddress = new Uri(baseUrl);
        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            PropertyNameCaseInsensitive = true
        };
        _jsonOptions.Converters.Add(new JsonStringEnumConverter(new UpperSnakeCaseNamingPolicy()));
    }

    public async Task<DocumentProcessResponse> ProcessDocumentAsync(Guid documentId, string filePath, CancellationToken cancellationToken)
    {
        await using var fileStream = File.OpenRead(filePath);
        using var content = new MultipartFormDataContent();
        var fileContent = new StreamContent(fileStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        content.Add(fileContent, "file", Path.GetFileName(filePath));
        content.Add(new StringContent(documentId.ToString()), "document_id");
        content.Add(new StringContent("web"), "source");

        using var response = await _httpClient.PostAsync("/process-document", content, cancellationToken);
        response.EnsureSuccessStatusCode();

        var result = await response.Content.ReadFromJsonAsync<DocumentProcessResponse>(_jsonOptions, cancellationToken);
        if (result is null)
        {
            throw new InvalidOperationException("La respuesta del motor IA es inválida.");
        }

        return result;
    }
}
