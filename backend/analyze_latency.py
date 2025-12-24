"""
Latency Analysis Script for GPT Realtime Voice Application
Analyzes log files and generates performance metrics report.

Usage:
    python analyze_latency.py                    # Analyze today's logs
    python analyze_latency.py logs/latency_20241224.log  # Analyze specific log
    python analyze_latency.py --all              # Analyze all logs
"""

import os
import sys
import re
import json
import statistics
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class LatencyAnalyzer:
    """Analyzes latency logs and generates metrics"""
    
    def __init__(self):
        self.sessions: Dict[str, dict] = defaultdict(lambda: {
            'connection_latency': None,
            'requests': [],
            'total_duration': None,
        })
        self.metrics = {
            'connection_latency': [],
            'time_to_first_audio': [],
            'time_to_first_text': [],
            'total_response_time': [],
            'end_to_end': [],
            'speech_duration': [],
        }
        
    def parse_log_file(self, filepath: str):
        """Parse a single log file"""
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return
            
        print(f"Parsing: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                self._parse_line(line.strip())
                
    def _parse_line(self, line: str):
        """Parse a single log line and extract metrics"""
        if not line:
            return
            
        # Extract session ID
        session_match = re.search(r'\[(session_\d+)\]', line)
        if not session_match:
            return
        session_id = session_match.group(1)
        
        # Extract event type and metrics
        if 'CONNECTION_ESTABLISHED' in line:
            latency = self._extract_metric(line, 'latency')
            if latency:
                self.sessions[session_id]['connection_latency'] = latency
                self.metrics['connection_latency'].append(latency)
                
        elif 'SPEECH_ENDED' in line:
            duration = self._extract_metric(line, 'speech_duration')
            if duration:
                self.metrics['speech_duration'].append(duration)
                
        elif 'FIRST_AUDIO' in line:
            ttfa = self._extract_metric(line, 'time_to_first_audio')
            if ttfa:
                self.metrics['time_to_first_audio'].append(ttfa)
                self.sessions[session_id].setdefault('requests', []).append({
                    'ttfa': ttfa
                })
                
        elif 'FIRST_TEXT' in line:
            ttft = self._extract_metric(line, 'time_to_first_text')
            if ttft:
                self.metrics['time_to_first_text'].append(ttft)
                
        elif 'RESPONSE_DONE' in line:
            total_time = self._extract_metric(line, 'total_response_time')
            e2e = self._extract_metric(line, 'end_to_end')
            if total_time:
                self.metrics['total_response_time'].append(total_time)
            if e2e:
                self.metrics['end_to_end'].append(e2e)
                
    def _extract_metric(self, line: str, metric_name: str) -> Optional[float]:
        """Extract a numeric metric from a log line"""
        pattern = rf'{metric_name}=(\d+\.?\d*)ms'
        match = re.search(pattern, line)
        if match:
            return float(match.group(1))
        return None
        
    def calculate_statistics(self, values: List[float]) -> dict:
        """Calculate statistics for a list of values"""
        if not values:
            return {
                'count': 0,
                'min': None,
                'max': None,
                'mean': None,
                'median': None,
                'p50': None,
                'p90': None,
                'p95': None,
                'p99': None,
                'std_dev': None,
            }
            
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        return {
            'count': n,
            'min': round(min(values), 2),
            'max': round(max(values), 2),
            'mean': round(statistics.mean(values), 2),
            'median': round(statistics.median(values), 2),
            'p50': round(sorted_values[int(n * 0.50)], 2) if n > 0 else None,
            'p90': round(sorted_values[int(n * 0.90)], 2) if n >= 10 else None,
            'p95': round(sorted_values[int(n * 0.95)], 2) if n >= 20 else None,
            'p99': round(sorted_values[int(n * 0.99)], 2) if n >= 100 else None,
            'std_dev': round(statistics.stdev(values), 2) if n > 1 else 0,
        }
        
    def generate_report(self) -> str:
        """Generate a formatted report of all metrics"""
        lines = []
        lines.append("")
        lines.append("=" * 70)
        lines.append("   GPT REALTIME LATENCY ANALYSIS REPORT")
        lines.append("   Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("=" * 70)
        lines.append("")
        
        # Summary
        total_requests = len(self.metrics['time_to_first_audio'])
        total_sessions = len(self.sessions)
        lines.append(f"SUMMARY")
        lines.append("-" * 40)
        lines.append(f"   Total Sessions:    {total_sessions}")
        lines.append(f"   Total Requests:    {total_requests}")
        lines.append("")
        
        # Key Metrics Table
        metrics_to_show = [
            ('Connection Latency', 'connection_latency'),
            ('Time to First Audio (TTFA)', 'time_to_first_audio'),
            ('Time to First Text (TTFT)', 'time_to_first_text'),
            ('Total Response Time', 'total_response_time'),
            ('End-to-End Latency', 'end_to_end'),
            ('Speech Duration', 'speech_duration'),
        ]
        
        for display_name, metric_key in metrics_to_show:
            values = self.metrics.get(metric_key, [])
            stats = self.calculate_statistics(values)
            
            lines.append(f"{display_name}")
            lines.append("-" * 40)
            
            if stats['count'] == 0:
                lines.append("   No data available")
            else:
                lines.append(f"   Count:      {stats['count']}")
                lines.append(f"   Min:        {stats['min']} ms")
                lines.append(f"   Max:        {stats['max']} ms")
                lines.append(f"   Mean:       {stats['mean']} ms")
                lines.append(f"   Median:     {stats['median']} ms")
                lines.append(f"   Std Dev:    {stats['std_dev']} ms")
                if stats['p90']:
                    lines.append(f"   P90:        {stats['p90']} ms")
                if stats['p95']:
                    lines.append(f"   P95:        {stats['p95']} ms")
                if stats['p99']:
                    lines.append(f"   P99:        {stats['p99']} ms")
            lines.append("")
        
        # Performance Assessment
        ttfa_values = self.metrics['time_to_first_audio']
        if ttfa_values:
            avg_ttfa = statistics.mean(ttfa_values)
            lines.append("PERFORMANCE ASSESSMENT")
            lines.append("-" * 40)
            
            if avg_ttfa < 300:
                rating = "EXCELLENT"
                emoji = "🟢"
            elif avg_ttfa < 500:
                rating = "GOOD"
                emoji = "🟡"
            elif avg_ttfa < 800:
                rating = "ACCEPTABLE"
                emoji = "🟠"
            else:
                rating = "NEEDS IMPROVEMENT"
                emoji = "🔴"
                
            lines.append(f"   {emoji} Time to First Audio: {rating}")
            lines.append(f"      Average TTFA of {avg_ttfa:.0f}ms")
            lines.append("")
            
            # Recommendations
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 40)
            if avg_ttfa > 500:
                lines.append("   - Consider using a region closer to your users")
                lines.append("   - Check network latency to Azure")
                lines.append("   - Optimize audio chunk size")
            else:
                lines.append("   - Performance is within acceptable range")
                lines.append("   - Monitor for any degradation over time")
            lines.append("")
        
        lines.append("=" * 70)
        lines.append("")
        
        return "\n".join(lines)
    
    def export_json(self, filepath: str):
        """Export metrics as JSON"""
        data = {
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_sessions': len(self.sessions),
                'total_requests': len(self.metrics['time_to_first_audio']),
            },
            'metrics': {}
        }
        
        for metric_name, values in self.metrics.items():
            data['metrics'][metric_name] = {
                'raw_values': values,
                'statistics': self.calculate_statistics(values)
            }
            
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"Exported JSON report to: {filepath}")
        
    def export_csv(self, filepath: str):
        """Export metrics as CSV"""
        with open(filepath, 'w') as f:
            # Header
            f.write("Metric,Count,Min,Max,Mean,Median,StdDev,P90,P95,P99\n")
            
            for metric_name, values in self.metrics.items():
                stats = self.calculate_statistics(values)
                f.write(f"{metric_name},{stats['count']},{stats['min']},{stats['max']},"
                       f"{stats['mean']},{stats['median']},{stats['std_dev']},"
                       f"{stats['p90']},{stats['p95']},{stats['p99']}\n")
                
        print(f"Exported CSV report to: {filepath}")


def main():
    analyzer = LatencyAnalyzer()
    
    # Determine which logs to analyze
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            # Analyze all logs
            if os.path.exists(log_dir):
                for filename in sorted(os.listdir(log_dir)):
                    if filename.endswith('.log'):
                        analyzer.parse_log_file(os.path.join(log_dir, filename))
        elif sys.argv[1] == '--json':
            # Parse and export as JSON
            today = datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(log_dir, f'latency_{today}.log')
            analyzer.parse_log_file(log_file)
            analyzer.export_json(os.path.join(log_dir, f'metrics_{today}.json'))
            return
        elif sys.argv[1] == '--csv':
            # Parse and export as CSV
            today = datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(log_dir, f'latency_{today}.log')
            analyzer.parse_log_file(log_file)
            analyzer.export_csv(os.path.join(log_dir, f'metrics_{today}.csv'))
            return
        else:
            # Analyze specific file
            analyzer.parse_log_file(sys.argv[1])
    else:
        # Analyze today's log
        today = datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(log_dir, f'latency_{today}.log')
        analyzer.parse_log_file(log_file)
    
    # Generate and print report
    report = analyzer.generate_report()
    print(report)
    
    # Also save report to file
    report_file = os.path.join(log_dir, f'report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
    os.makedirs(log_dir, exist_ok=True)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"Report saved to: {report_file}")


if __name__ == '__main__':
    main()

