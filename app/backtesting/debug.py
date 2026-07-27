from app.strategy.trend_following.breakout.rejection import BreakoutRejectionAnalyzer


class PrintDebug:

    @staticmethod
    def print_breakout_rejection(result) -> None:
        breakout_rejection: BreakoutRejectionAnalyzer | None = result.get("breakout_rejection")
        if breakout_rejection and breakout_rejection.items:
            print("\nBreakout Rejection Summary")
            for group, reasons in breakout_rejection.summary().items():
                print(f"\n  {group}")
                for reason, count, pct in reasons:
                    print(f"    {reason:<20} {count:>4} ({pct:5.1f}%)")
            
            print("\nRejected Value Range:")
            for name, values in breakout_rejection.metric_summary().items():
                print(
                    f"    {name:<20} "
                    f"    avg={sum(values)/len(values):.2f} "
                    f"    min={min(values):.2f} "
                    f"    max={max(values):.2f}"
                )

    @staticmethod
    def print_breakout_pipeline(result) -> None:
        stats = result.get("pipeline_stats")
        if stats:
            total = stats.candidates or 1
            hard_pct = stats.hard_pass / total * 100
            soft_pct = stats.soft_pass / stats.hard_pass * 100 if stats.hard_pass else 0
            setup_pct = stats.setup_candidates / stats.soft_pass * 100 if stats.soft_pass else 0
            print("\nBREAKOUT PIPELINE")
            print(f"    {'Candidates':<20} {stats.candidates}")
            print(f"        {'LONG':<18} {stats.long_candidates}")
            print(f"        {'SHORT':<18} {stats.short_candidates}")
            print(f"    {'Hard pass':<20} {stats.hard_pass} ({hard_pct:.1f}%)")
            print(f"    {'Soft pass':<20} {stats.soft_pass} ({soft_pct:.1f}%)")
            print(f"    {'Setup candidates':<20} {stats.setup_candidates} ({setup_pct:.1f}%)")
            print(f"    {'Setup built':<20} {stats.setup_built}")
            print(f"        {'Skip no data':<20} {stats.setup_skip_no_data}")
            print(f"        {'Skip no entry':<20} {stats.setup_skip_no_entry}")
            print(f"        {'Skip score':<20} {stats.setup_skip_score}")
            if stats.setup_skip_score_values:
                vals = stats.setup_skip_score_values
                print(f"    {'Skipped Score Range':<20} {min(vals):.0f}-{max(vals):.0f} avg={sum(vals)/len(vals):.0f}")
            print(f"    {'Signal built':<20} {stats.signal_built}")
            print(f"        {'skip':<20} {stats.signal_skip}")
            for reason, count in stats.signal_skip_reasons.most_common():
                print(f"    {'  ' + reason:<20} {count}")
            print(f"    {'Risk allowed':<20} {stats.risk_allowed}")
            print(f"    {'Order planned':<20} {stats.order_planned}")