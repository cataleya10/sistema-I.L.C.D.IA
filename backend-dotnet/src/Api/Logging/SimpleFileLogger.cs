using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;

namespace Api.Logging;

public sealed class SimpleFileLoggerProvider : ILoggerProvider
{
    private readonly string _filePath;
    private readonly long _maxFileSizeBytes;
    private readonly int _maxRetainedFiles;
    private readonly BlockingCollection<string> _queue = new();
    private readonly Thread _writerThread;

    public SimpleFileLoggerProvider(string filePath, long maxFileSizeBytes = 10 * 1024 * 1024, int maxRetainedFiles = 5)
    {
        _filePath = filePath;
        _maxFileSizeBytes = maxFileSizeBytes;
        _maxRetainedFiles = maxRetainedFiles;
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

    private void RotateIfNeeded()
    {
        try
        {
            if (!File.Exists(_filePath)) return;

            var info = new FileInfo(_filePath);
            if (info.Length < _maxFileSizeBytes) return;

            // Rotate: api.log -> api.log.1, api.log.1 -> api.log.2, etc.
            for (var i = _maxRetainedFiles - 1; i >= 1; i--)
            {
                var src = $"{_filePath}.{i}";
                var dst = $"{_filePath}.{i + 1}";
                if (File.Exists(src))
                {
                    if (i + 1 >= _maxRetainedFiles)
                        File.Delete(src);
                    else
                        File.Move(src, dst, overwrite: true);
                }
            }
            File.Move(_filePath, $"{_filePath}.1", overwrite: true);
        }
        catch
        {
            // Best-effort rotation — never crash the logger
        }
    }

    private void WriterLoop()
    {
        try
        {
            var lineCount = 0;
            using var stream = new FileStream(_filePath, FileMode.Append, FileAccess.Write, FileShare.Read);
            using var writer = new StreamWriter(stream);
            foreach (var line in _queue.GetConsumingEnumerable())
            {
                writer.WriteLine(line);
                writer.Flush();
                lineCount++;
                // Check rotation every 500 lines to avoid excessive stat calls
                if (lineCount % 500 == 0)
                {
                    writer.Flush();
                    stream.Flush();
                    if (stream.Length >= _maxFileSizeBytes)
                    {
                        writer.Close();
                        RotateIfNeeded();
                        // Re-open after rotation — exit out and restart the loop
                        // (BackgroundService will keep the thread alive)
                        break;
                    }
                }
            }
        }
        catch
        {
            // Swallow logging failures
        }

        // If we broke out of the inner loop for rotation, restart with a new file handle
        if (!_queue.IsAddingCompleted)
        {
            WriterLoop();
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

