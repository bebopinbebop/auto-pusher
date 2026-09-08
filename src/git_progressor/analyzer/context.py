from git_progressor.analyzer.models import PlannerContext, ProjectAnalysis


class PlannerContextBuilder:
    """Build a safe planner payload without reading repository contents."""

    def build(self, analysis: ProjectAnalysis) -> PlannerContext:
        return PlannerContext(
            project_id=analysis.project_id,
            source_revision=analysis.source_revision,
            analysis_hash=analysis.analysis_hash,
            languages=tuple(item.name for item in analysis.languages),
            frameworks_and_tools=tuple(
                item.name for item in analysis.frameworks_and_tools
            ),
            dependencies=analysis.dependencies,
            tests=analysis.tests,
            configuration_paths=tuple(item.path for item in analysis.configuration),
            infrastructure_paths=tuple(item.path for item in analysis.infrastructure),
            documentation_paths=tuple(item.path for item in analysis.documentation),
            entrypoints=analysis.entrypoints,
            modules=analysis.modules,
            important_files=analysis.important_files,
            warnings=analysis.warnings,
        )

