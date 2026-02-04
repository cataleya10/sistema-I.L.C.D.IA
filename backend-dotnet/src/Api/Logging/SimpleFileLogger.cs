using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;

namespace Api.Logging;

public sealed class SimpleFileLoggerProvider : ILoggerProvider
{
    private readonly string _filePath;
    private readonly BlockingCollection<string> _queue = new();
    private readonly Thread _writerThread;

    public SimpleFileLoggerProvider(string filePath)
    {
        _filePath = filePath;
        var directory = Path.GetDirectoryName(_filePath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }
        _writerThread = new Thread(WriterLoop)
        {
            IsBackground = true,
            Name = "SimpleFileLogger"
        };
        _writerThread.Start();
    }

    public ILogger CreateLogger(string categoryName) => new SimpleFileLogger(categoryName, _queue);

    public void Dispose()
    {
        _queue.CompleteAdding();
    }

    private void WriterLoop()
    {
        try
        {
            using var stream = new FileStream(_filePath, FileMode.Append, FileAccess.Write, FileShare.Read);
            using var writer = new StreamWriter(stream);
            foreach (var line in _queue.GetConsumingEnumerable())
            {
                writer.WriteLine(line);
                writer.Flush();
            }
        }
        catch
        {
            // Swallow logging failures
        }
    }
}

public sealed class SimpleFileLogger : ILogger
{
    private readonly string _category;
    private readonly BlockingCollection<string> _queue;

    public SimpleFileLogger(string category, BlockingCollection<string> queue)
    {
        _category = category;
        _queue = queue;
    }

    public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

    public bool IsEnabled(LogLevel logLevel) => logLevel != LogLevel.None;

    public void Log<TState>(
        LogLevel logLevel,
        EventId eventId,
        TState state,
        Exception? exception,
        Func<TState, Exception?, string> formatter)
    {
        if (!IsEnabled(logLevel))
        {
            return;
        }
        var message = formatter(state, exception);
        if (string.IsNullOrWhiteSpace(message) && exception is null)
        {
            return;
        }
        var timestamp = DateTime.UtcNow.ToString("O");
        var line = $"{timestamp} [{logLevel}] {_category} {message}";
        if (exception is not null)
        {
            line += $" | {exception.GetType().Name}: {exception.Message}";
        }
        _queue.Add(line);
    }
}

