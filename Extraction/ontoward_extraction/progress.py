from datetime import datetime, timezone


def display(results):
    if not results:
        return 'No saved extraction runs (not_started).'
    blocks=[]
    for status in results:
        index=status['index'];current=index['current_file']
        lines=[f"Run {status['run_id']} | {status['state']} | {status['provider']} | phase={status['phase']}",
            f"  Index: {index['files_completed']:,}/{index['files_total']:,} files complete; {index['rows_committed']:,} records committed"]
        if status.get('augmentation'):
            augmentation=status['augmentation']
            lines.pop()
            maximum=augmentation['request_budget_history'][-1]['maximum'] if augmentation['request_budget_history'] else 'unset'
            lines.append(f"  Augmentation transmissions: {augmentation['model_transmissions']}/{maximum} (including retries)")
        if current:
            lines.append(f"  Current file: {current['path']}")
            lines.append(f"  File checkpoint: {current['rows_committed']:,} records committed")
        for phase,counts in status['jobs_by_phase'].items():
            lines.append('  '+phase+': '+', '.join(f'{key}={value:,}' for key,value in counts.items()))
        lines.append('  Requests: '+(', '.join(f'{key}={value:,}' for key,value in status['requests'].items()) or '0'))
        lines.append(f"  Model calls recorded: {sum(row['calls'] for row in status['usage']):,}")
        if status['updated_at']:
            lines.append('  Updated: '+datetime.fromtimestamp(status['updated_at'],timezone.utc).isoformat(timespec='seconds'))
        if status['error']:
            lines.append('  Error: '+status['error'])
        for row in status.get('job_errors',[]):
            lines.append(f"  Job {row['job_id'][:12]} ({row['phase']}, attempts={row['attempt_count']}): {row['error']}")
        if status.get('recovery'):
            lines.append('  Recovered raw index from: '+status['recovery']['source_run_id'])
        lines.append('  Later worksets and ETA may be unknown.' if status.get('augmentation') else
            '  File counts are not an overall completion percentage; later worksets and ETA may be unknown.')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
