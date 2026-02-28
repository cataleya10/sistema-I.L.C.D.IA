using Microsoft.AspNetCore.Mvc;
using System.IO;
using System.Threading.Tasks;
using System;
using System.Linq;
using Api.Clients;

namespace Api.Controllers
{
    [ApiController]
    [Route("api/ocr")]
    public class OcrController : ControllerBase
    {
        [HttpPost("upload")]
        public async Task<IActionResult> UploadImage()
        {
            var file = Request.Form.Files[0];
            if (file == null || file.Length == 0)
                return BadRequest("No file uploaded.");

            var allowedTypes = new[] { "image/jpeg", "image/png", "application/pdf" };
            if (!allowedTypes.Contains(file.ContentType))
                return BadRequest("Tipo de archivo no permitido. Solo JPG, PNG o PDF.");
            if (file.Length > 5 * 1024 * 1024)
                return BadRequest("El archivo excede el tamaño máximo permitido (5MB).");

            var tempPath = Path.Combine(Path.GetTempPath(), Guid.NewGuid() + Path.GetExtension(file.FileName));
            using (var stream = new FileStream(tempPath, FileMode.Create))
            {
                await file.CopyToAsync(stream);
            }

            var pythonOcrClient = new PythonOcrClient("http://localhost:5000/api/ocr");
            object? resultado = null;
            try
            {
                resultado = await pythonOcrClient.ProcessImageAsync(tempPath);
            }
            catch (Exception ex)
            {
                if (global::System.IO.File.Exists(tempPath))
                    global::System.IO.File.Delete(tempPath);
                return StatusCode(502, $"Error al procesar la imagen: {ex.Message}");
            }

            if (global::System.IO.File.Exists(tempPath))
                global::System.IO.File.Delete(tempPath);

            var dict = resultado as IDictionary<string, object>;
            var fields = dict != null && dict.ContainsKey("fields") ? dict["fields"] as IEnumerable<object> : null;
            var tablas = fields != null ? fields.Where(f => ((IDictionary<string, object>)f)["key"].ToString() == "tabla_celdas").ToList() : null;
            var tipo_documento = dict != null && dict.ContainsKey("document_type") ? dict["document_type"] : null;
            var confianza = dict != null && dict.ContainsKey("confidence") ? dict["confidence"] : null;
            var advertencias = dict != null && dict.ContainsKey("warnings") ? dict["warnings"] : null;

            var response = new {
                campos = fields,
                tablas = tablas,
                tipo_documento = tipo_documento,
                confianza = confianza,
                advertencias = advertencias
            };
            return Ok(response);
        }
    }
}
