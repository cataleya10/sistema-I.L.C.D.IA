using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;
using System.IO;
using Newtonsoft.Json;

namespace Api.Clients
{
    public class PythonOcrClient
    {
        private readonly HttpClient _httpClient;
        private readonly string _serviceUrl;

        public PythonOcrClient(string serviceUrl)
        {
            _serviceUrl = serviceUrl;
            _httpClient = new HttpClient();
        }

        public async Task<dynamic> ProcessImageAsync(string imagePath)
        {
            using var form = new MultipartFormDataContent();
            using var fileStream = File.OpenRead(imagePath);
            var fileContent = new StreamContent(fileStream);
            fileContent.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg"); // Ajusta el tipo si usas PNG/PDF
            form.Add(fileContent, "file", Path.GetFileName(imagePath));

            var response = await _httpClient.PostAsync(_serviceUrl + "/process", form);
            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<dynamic>(json);
        }
    }
}
