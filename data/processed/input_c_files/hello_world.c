#include <stdio.h>
#include <string.h>

int main() {
    char name[100];
    if (scanf("%99s", name) == 1) {
        printf("Hello, %s!\n", name);
    }
    return 0;
}
