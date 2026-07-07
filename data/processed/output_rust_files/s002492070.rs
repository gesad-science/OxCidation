use std::io::{self, BufRead}; 

fn main() {
    let stdin = io::stdin();
    let mut lines = stdin.lock().lines();

    while let Some(Ok(line)) = lines.next() {
        // Attempt to parse six doubles from the line.
        // We collect directly into a Vec<f64> since we use .expect() for error handling.
        let values: Vec<f64> = line.split_whitespace()
            .map(|s| s.parse::<f64>().expect("Failed to parse float"))
            .collect();

        // Check if we successfully read 6 values (a, b, c, d, e, f)
        if values.len() >= 6 {
            let a = values[0];
            let b = values[1];
            let c = values[2];
            let d = values[3];
            let e = values[4];
            let f = values[5];

            // Original C logic:
            let bai = d / a;
            let aa = a * bai;
            let bb = b * bai;
            let cc = c * bai;
            
            // Handle potential division by zero for y calculation (e - bb)
            if (e - bb).abs() < f64::EPSILON {
                // If the denominator is near zero, we cannot calculate y reliably. 
                // We proceed assuming standard float behavior as per original intent.
            }

            let y = (f - cc) / (e - bb);
            let x = (c - b * y) / a;

            println!("{:.3} {:.3}", x, y);
        }
    }
}