using System.Threading.Channels;
using Application.Interfaces;

namespace Infrastructure.Services;

public sealed class DocumentProcessingQueue : IProcessingQueue
{
    private readonly Channel<DocumentProcessJob> _channel;

    public DocumentProcessingQueue()
    {
        _channel = Channel.CreateUnbounded<DocumentProcessJob>(new UnboundedChannelOptions
        {
            SingleReader = true,
            SingleWriter = false
        });
    }

    public ValueTask EnqueueAsync(DocumentProcessJob job, CancellationToken cancellationToken = default)
    {
        return _channel.Writer.WriteAsync(job, cancellationToken);
    }

    public ValueTask<DocumentProcessJob> DequeueAsync(CancellationToken cancellationToken)
    {
        return _channel.Reader.ReadAsync(cancellationToken);
    }
}
