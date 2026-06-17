use std::io::{self, Write};

// Define a structure to hold the global state variables used in the C code.
struct PrimeCounter {
    count: i32,
    prime: [i32; 500000],
    primebool: [bool; 500000],
}

impl PrimeCounter {
    // Initialize the state variables mimicking static global initialization.
    fn new() -> Self {
        let mut prime = [0; 500000];
        let mut primebool = [false; 500000];
        prime[0] = 2;
        prime[1] = 3;
        primebool[0] = true;
        primebool[1] = true;
        PrimeCounter {
            count: 0,
            prime,
            primebool,
        }
    }

    // Mimics the global reset function.
    fn reset(&mut self) {
        self.count = 0;
    }

    // Mimics primesearch(int x).
    // Finds the next prime number starting search from x, skipping multiples of i.
    fn primesearch(&self, x: i32) -> i32 {
        let mut i = 3;
        let sq = (x as f64).sqrt() as i32;

        // The loop structure is identical to the C code:
        while i <= sq { 
            if x % i == 0 {
                // If composite, recursively search for the next prime starting from x + 2.
                return self.primesearch(x + 2);
            }
            i += 2;
        }
        // If no divisors found up to sqrt(x), it is prime.
        x
    }

    // Mimics primecount(int i, int n).
    fn primecount(&mut self, i: usize, n: i32) {
        // Check if the current index 'i' has already been marked as prime (or calculated).
        if !self.primebool[i] {
            // Calculate the next potential prime using the previous stored prime.
            // Note: The C code uses prime[i-1]+2, which assumes i > 0 and that prime[i-1] is valid.
            let prev_prime = if i == 0 { 0 } else { self.prime[i - 1] };
            self.prime[i] = self.primesearch(prev_prime + 2);
            self.primebool[i] = true;
        }

        // Check if the found prime is within the limit n.
        if self.prime[i] <= n {
            self.count += 1;
            // Recurse to check the next index i+1.
            self.primecount(i + 1, n);
        }
    }

    // Main logic loop mimicking main().
    fn run(&mut self) -> io::Result<()> {
        let mut input_buffer = String::new();
        
        // Read integers until EOF.
        loop {
            input_buffer.clear();
            match io::stdin().read_line(&mut input_buffer) { 
                Ok(0) => break, // EOF reached
                Ok(_) => { 
                    let n: i32 = match input_buffer.trim().parse() {
                        Ok(num) => num,
                        Err(_) => continue, // Skip if parsing fails
                    };

                    if n > 1 {
                        // Start prime counting from index 0.
                        self.primecount(0, n);
                        println!("{}", self.count);
                        self.reset();
                    } else {
                        // If N <= 1, no primes are counted, so we do nothing here.
                    }
                },
                Err(e) => return Err(e), // Handle IO errors
            }
        }
        Ok(())
    }
}

fn main() -> io::Result<()> {
    let mut counter = PrimeCounter::new();
    counter.run()?;
    Ok(())
}