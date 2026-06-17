use std::io::{self, Read};
use std::cmp;

fn main() -> io::Result<()> {
    // Read all input from stdin at once to handle automated testing environments
    let mut buffer = String::new();
    std::io::stdin().read_to_string(&mut buffer)?;
    
    // Use trim() first to remove potential leading/trailing whitespace, including newlines.
    let lines: Vec<&str> = buffer.trim().split('\n').collect();

    if lines.is_empty() {
        return Ok(());
    }

    // --- 1. Parse W and N (from the first line) ---
    let parts_wn: Vec<i32> = lines[0].trim()
        .split_whitespace()
        .filter_map(|s| s.parse::<i32>().ok())
        .collect();

    if parts_wn.len() < 2 {
        // If input is malformed, exit gracefully
        return Ok(());
    }
    let mut w = parts_wn[0];
    let mut n = parts_wn[1];

    // Initialize the array temp[31]. Indices 1 through 30 are used.
    let mut temp: [i32; 31] = [0; 31];
    for i in 1..=30 {
        temp[i as usize] = i;
    }

    // --- 2. Process Swaps (from subsequent lines) ---
    
    // Calculate the number of swaps to process: min(N, available lines - 1).
    let max_swaps_from_n = n.max(0) as usize; // Ensure non-negative conversion
    let available_swap_lines = lines.len().saturating_sub(1);

    // Use std::cmp::min to correctly compare two usize values
    let num_swap_inputs = cmp::min(max_swaps_from_n, available_swap_lines);


    for k in 0..num_swap_inputs {
        // The swap data is on line index k + 1.
        let line = lines[k + 1];
        
        // Parse the comma-separated pair a,b
        let parts: Vec<&str> = line.trim().split(',').collect();

        if parts.len() >= 2 {
            // Use unwrap_or(0) for robust parsing of indices
            let a_parsed: i32 = parts[0].trim().parse().unwrap_or(0);
            let b_parsed: i32 = parts[1].trim().parse().unwrap_or(0);

            // Check if indices are within the valid range [1, 30]
            if a_parsed >= 1 && a_parsed <= 30 && b_parsed >= 1 && b_parsed <= 30 {
                let a = a_parsed as usize;
                let b = b_parsed as usize;

                // Swapping logic: temp[a] <-> temp[b]
                let temp1 = temp[a];
                temp[a] = temp[b];
                temp[b] = temp1;
            }
        }
    }

    Ok(())
}