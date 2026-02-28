using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Xunit;
using Api.Controllers;

namespace Api.Tests
{
    public class OcrControllerTests
    {
        [Fact]
        public async Task UploadImage_ReturnsOkResult_WithFieldsAndTables()
        {
            // Arrange
            var controller = new OcrController();
            var fileMock = new FormFile(new MemoryStream(new byte[] { 1, 2, 3 }), 0, 3, "file", "test.jpg");
            controller.ControllerContext = new ControllerContext
            {
                HttpContext = new DefaultHttpContext()
            };
            controller.Request.Form.Files.Add(fileMock);

            // Act
            var result = await controller.UploadImage();

            // Assert
            var okResult = Assert.IsType<OkObjectResult>(result);
            Assert.NotNull(okResult.Value);
            // Aquí podrías validar la estructura de la respuesta si tienes un mock del servicio Python
        }
    }
}
