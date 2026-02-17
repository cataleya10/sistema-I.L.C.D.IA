namespace Application.DTOs;

public sealed record OnlineLearningStatsDto(
    bool Enabled,
    string StatsPath,
    string DatasetPath,
    string ModelPath,
    string AliasPath,
    DateTimeOffset? UpdatedAtUtc,
    int DatasetSamples,
    OnlineLearningTotalsDto Totals,
    IReadOnlyDictionary<string, int> ByReason,
    IReadOnlyDictionary<string, OnlineLearningByTypeDto> ByDocumentType,
    OnlineLearningEventDto? LastEvent,
    IReadOnlyList<OnlineLearningEventDto> RecentEvents
);

public sealed record OnlineLearningTotalsDto(
    int Attempted,
    int Trained,
    int Skipped
);

public sealed record OnlineLearningByTypeDto(
    int Attempted,
    int Trained,
    int Skipped
);

public sealed record OnlineLearningEventDto(
    DateTimeOffset? TimestampUtc,
    string DocumentId,
    string DocumentType,
    string Status,
    decimal Confidence,
    bool Trained,
    string Reason,
    int Labels
);
