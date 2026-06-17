use std::io::{self, Write};

fn main() -> io::Result<()> {
    let mut input = String::new();
    // Read the integer N from standard input
    io::stdin().read_line(&mut input)?;
    
    // Trim whitespace and parse N. Handle potential parsing errors.
    let n: i32 = match input.trim().parse() {
        Ok(num) => num,
        Err(_) => return Ok(()), // Exit if parsing fails
    };

    // Initialize 'a' as a floating-point number (f64 for precision)
    let mut a: f64 = 100000.0;

    for _ in 0..n {
        // a = a * 1.05;
        a *= 1.05;

        // C logic: if(a%1000>0)
        // In Rust, we use the standard float modulo operator.
        if (a % 1000.0) > 0.0 {
            // a = a/1000*1000+1000;
            
            // Calculate floor(a / 1000) * 1000 + 1000
            let truncated_a = (a / 1000.0).floor() * 1000.0;
            a = truncated_a + 1000.0;
        }
    }

    // printf("%d\n",a); 
    // Print the final float 'a' cast/truncated to an integer.
    println!("{}", a as i32);

    Ok(())
}