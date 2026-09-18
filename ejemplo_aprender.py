# ¡Bienvenido a tu primer programa en Prig IDE!
# Puedes ejecutar este código presionando el botón "Ejecutar" o Ctrl+Enter.

def saludar(nombre):
    print(f"¡Hola, {nombre}! Bienvenido a la programación en Ubuntu.")

def calcular_suma(a, b):
    resultado = a + b
    print(f"La suma de {a} + {b} es igual a: {resultado}")
    return resultado

if __name__ == "__main__":
    saludar("Estudiante")
    calcular_suma(10, 25)
